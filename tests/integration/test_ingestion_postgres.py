"""Complete ingestion write-path tests against real PostgreSQL adapters."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from mnemo.entities import DeterministicEntityResolver
from mnemo.ingestion import CandidateIngestionOutcome, IngestionService
from mnemo.lifecycle.engine import LifecycleEngine
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.persistence.postgres.repositories import (
    PostgresCaptureRepository,
    PostgresEntityRepository,
    PostgresMemoryRepository,
)
from mnemo.persistence.postgres.session import create_postgres_engine, create_session_factory

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).parents[2]
USER_ID = "ingestion-postgres-user"
OTHER_USER_ID = "other-ingestion-user"
NOW = datetime(2026, 10, 9, 15, tzinfo=UTC)


def _id(number: int) -> UUID:
    return UUID(int=10_000 + number)


@pytest.fixture(scope="session")
def ingestion_postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("MNEMO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MNEMO_TEST_DATABASE_URL is required for PostgreSQL integration tests")

    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(ROOT / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(alembic_config, "head")

    engine = create_postgres_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


@pytest.fixture(autouse=True)
def clean_ingestion_database(ingestion_postgres_engine: Engine) -> Iterator[None]:
    with ingestion_postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE memories, captures, entities CASCADE"))
    yield


@pytest.fixture
def ingestion_repositories(
    ingestion_postgres_engine: Engine,
) -> tuple[
    PostgresCaptureRepository,
    PostgresEntityRepository,
    PostgresMemoryRepository,
]:
    factory: sessionmaker[Session] = create_session_factory(ingestion_postgres_engine)
    return (
        PostgresCaptureRepository(factory),
        PostgresEntityRepository(factory),
        PostgresMemoryRepository(factory),
    )


class FakeExtractor:
    def __init__(self, candidates: Sequence[CandidateMemory]) -> None:
        self.candidates = tuple(candidates)

    def extract(self, capture: Capture) -> Sequence[CandidateMemory]:
        return self.candidates


@dataclass(frozen=True)
class FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


def _capture(number: int, text_value: str, *, user_id: str = USER_ID) -> Capture:
    return Capture(
        id=_id(number),
        user_id=user_id,
        source_type=SourceType.TEXT,
        raw_text=text_value,
        captured_at=NOW + timedelta(minutes=number),
        created_at=NOW + timedelta(minutes=number),
    )


def _candidate(
    *,
    kind: MemoryKind,
    subject: str,
    subject_type: EntityType,
    predicate: str,
    value: object,
    category: str | None = None,
    occurred_at: datetime | None = None,
) -> CandidateMemory:
    return CandidateMemory(
        kind=kind,
        category=category,
        subject=subject,
        subject_type=subject_type,
        predicate=predicate,
        value=value,
        occurred_at=occurred_at,
    )


def _service(
    *,
    extractor: FakeExtractor,
    repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
) -> IngestionService:
    captures, entities, memories = repositories
    return IngestionService(
        extractor=extractor,
        entity_resolver=DeterministicEntityResolver(entities),
        capture_repository=captures,
        entity_repository=entities,
        memory_repository=memories,
        clock=FixedClock(NOW),
        lifecycle_engine=LifecycleEngine(),
    )


def test_birthday_fact_ingests_end_to_end_and_retry_is_noop(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
) -> None:
    candidate = _candidate(
        kind=MemoryKind.FACT,
        subject="Kevin",
        subject_type=EntityType.PERSON,
        predicate="birthday",
        value="March 12",
    )
    capture = _capture(1, "Kevin's birthday is March 12.")
    service = _service(
        extractor=FakeExtractor([candidate]),
        repositories=ingestion_repositories,
    )
    captures, entities, memories = ingestion_repositories

    first = service.ingest(capture)
    retry = service.ingest(capture)

    assert first.candidate_results[0].outcome == CandidateIngestionOutcome.PERSISTED
    assert retry.candidate_results[0].outcome == CandidateIngestionOutcome.NOOP
    assert captures.get(user_id=USER_ID, capture_id=capture.id) == capture
    assert len(entities.list_for_user(user_id=USER_ID)) == 1
    active = memories.list_active(user_id=USER_ID, kind=MemoryKind.FACT)
    assert len(active) == 1
    assert active[0].source_capture_id == capture.id


def test_later_parking_capture_atomically_supersedes_prior_state(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
) -> None:
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.CURRENT_STATE,
                subject="my car",
                subject_type=EntityType.VEHICLE,
                predicate="parked_at",
                value="A1",
            )
        ]
    )
    service = _service(extractor=extractor, repositories=ingestion_repositories)
    _, _, memories = ingestion_repositories

    first = service.ingest(_capture(10, "I parked at A1."))
    first_id = first.candidate_results[0].memory_id
    assert first_id is not None
    first_memory = memories.get(user_id=USER_ID, memory_id=first_id)
    assert first_memory is not None
    assert first_memory.memory_key is not None

    extractor.candidates = (
        _candidate(
            kind=MemoryKind.CURRENT_STATE,
            subject="my car",
            subject_type=EntityType.VEHICLE,
            predicate="parked_at",
            value="B7",
        ),
    )
    changed = service.ingest(_capture(11, "I parked at B7."))
    replacement_id = changed.candidate_results[0].memory_id
    assert replacement_id is not None

    historical = memories.get(user_id=USER_ID, memory_id=first_id)
    assert historical is not None
    assert historical.status == MemoryStatus.SUPERSEDED
    assert historical.superseded_by_id == replacement_id
    active = memories.list_active(user_id=USER_ID, memory_key=first_memory.memory_key)
    assert [memory.id for memory in active] == [replacement_id]


def test_duplicate_event_retry_becomes_noop(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
) -> None:
    event = _candidate(
        kind=MemoryKind.EVENT,
        subject="me",
        subject_type=EntityType.PERSON,
        predicate="bench_press",
        value={"weight_lb": 185, "reps": 5},
        occurred_at=NOW - timedelta(hours=1),
    )
    capture = _capture(20, "Bench press 185 lb x 5.")
    service = _service(
        extractor=FakeExtractor([event]),
        repositories=ingestion_repositories,
    )
    _, _, memories = ingestion_repositories

    service.ingest(capture)
    retry = service.ingest(capture)

    assert retry.candidate_results[0].outcome == CandidateIngestionOutcome.NOOP
    assert len(memories.list_active(user_id=USER_ID, kind=MemoryKind.EVENT)) == 1


def test_costco_capture_persists_three_intents_with_shared_entity_and_source(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
) -> None:
    candidates = [
        _candidate(
            kind=MemoryKind.INTENT,
            category="shopping:costco",
            subject="me",
            subject_type=EntityType.PERSON,
            predicate="buy",
            value=item,
        )
        for item in ("eggs", "milk", "paper towels")
    ]
    capture = _capture(30, "Next Costco trip: buy eggs, milk, and paper towels.")
    service = _service(
        extractor=FakeExtractor(candidates),
        repositories=ingestion_repositories,
    )
    _, entities, memories = ingestion_repositories

    result = service.ingest(capture)

    assert [item.outcome for item in result.candidate_results] == [
        CandidateIngestionOutcome.PERSISTED,
        CandidateIngestionOutcome.PERSISTED,
        CandidateIngestionOutcome.PERSISTED,
    ]
    assert len(entities.list_for_user(user_id=USER_ID)) == 1
    active = memories.list_active(user_id=USER_ID, kind=MemoryKind.INTENT)
    assert len(active) == 3
    assert len({memory.subject_entity_id for memory in active}) == 1
    assert {memory.source_capture_id for memory in active} == {capture.id}


@pytest.mark.parametrize(
    ("entities", "expected"),
    [
        (
            [
                Entity(
                    id=_id(41),
                    user_id=USER_ID,
                    type=EntityType.PERSON,
                    canonical_name="Alex",
                ),
                Entity(
                    id=_id(42),
                    user_id=USER_ID,
                    type=EntityType.PERSON,
                    canonical_name="Alex",
                ),
            ],
            CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY,
        ),
        (
            [
                Entity(
                    id=_id(43),
                    user_id=USER_ID,
                    type=EntityType.ORGANIZATION,
                    canonical_name="Alex",
                )
            ],
            CandidateIngestionOutcome.BLOCKED_ENTITY_TYPE_CONFLICT,
        ),
    ],
)
def test_unsafe_preexisting_identity_blocks_postgres_memory_write(
    entities: list[Entity],
    expected: CandidateIngestionOutcome,
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
) -> None:
    _, entity_repository, memories = ingestion_repositories
    for entity in entities:
        entity_repository.add(user_id=USER_ID, entity=entity)
    service = _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    kind=MemoryKind.FACT,
                    subject="Alex",
                    subject_type=EntityType.PERSON,
                    predicate="birthday",
                    value="May 5",
                )
            ]
        ),
        repositories=ingestion_repositories,
    )

    outcome = service.ingest(_capture(40, "Alex's birthday is May 5.")).candidate_results[0]

    assert outcome.outcome == expected
    assert memories.list_active(user_id=USER_ID) == ()


def test_ingestion_keeps_entities_and_memories_isolated_by_user(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
) -> None:
    _, entities, memories = ingestion_repositories
    foreign = Entity(
        id=_id(50),
        user_id=OTHER_USER_ID,
        type=EntityType.PERSON,
        canonical_name="Kevin",
    )
    entities.add(user_id=OTHER_USER_ID, entity=foreign)
    service = _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    kind=MemoryKind.FACT,
                    subject="Kevin",
                    subject_type=EntityType.PERSON,
                    predicate="birthday",
                    value="March 12",
                )
            ]
        ),
        repositories=ingestion_repositories,
    )

    service.ingest(_capture(50, "Kevin's birthday is March 12."))

    own_entities = entities.list_for_user(user_id=USER_ID)
    assert len(own_entities) == 1
    assert own_entities[0].id != foreign.id
    assert entities.list_for_user(user_id=OTHER_USER_ID) == (foreign,)
    assert len(memories.list_active(user_id=USER_ID)) == 1
    assert memories.list_active(user_id=OTHER_USER_ID) == ()
