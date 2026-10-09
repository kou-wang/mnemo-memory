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

from mnemo.answers import (
    NO_EVIDENCE_MESSAGE,
    RecallAnswerOutcome,
    RecallAnswerService,
    SynthesizedAnswer,
)
from mnemo.entities import DeterministicEntityResolver
from mnemo.ingestion import CandidateIngestionOutcome, IngestionService
from mnemo.lifecycle.engine import LifecycleEngine
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.persistence.postgres.repositories import (
    PostgresCaptureRepository,
    PostgresEntityRepository,
    PostgresMemoryQueryRepository,
    PostgresMemoryRepository,
)
from mnemo.persistence.postgres.session import create_postgres_engine, create_session_factory
from mnemo.recall import (
    RecallExecutionOutcome,
    RecallMode,
    RecallOrchestrationService,
    RecallOutcome,
    RecallPlan,
    RecallPlanOutcome,
    StructuredRecallRequest,
    StructuredRecallService,
)

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


@pytest.fixture
def query_repository(ingestion_postgres_engine: Engine) -> PostgresMemoryQueryRepository:
    return PostgresMemoryQueryRepository(create_session_factory(ingestion_postgres_engine))


class FakeExtractor:
    def __init__(self, candidates: Sequence[CandidateMemory]) -> None:
        self.candidates = tuple(candidates)

    def extract(self, capture: Capture) -> Sequence[CandidateMemory]:
        return self.candidates


class FakeRecallPlanner:
    def __init__(self, plan_result: RecallPlan) -> None:
        self.plan_result = plan_result

    def plan(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallPlan:
        return self.plan_result


class FakeAnswerSynthesizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Memory, ...], datetime]] = []

    def synthesize(
        self,
        *,
        question: str,
        evidence: tuple[Memory, ...],
        asked_at: datetime,
    ) -> SynthesizedAnswer:
        self.calls.append((question, evidence, asked_at))
        return SynthesizedAnswer(
            text="Grounded answer from supplied evidence.",
            cited_memory_ids=tuple(memory.id for memory in evidence),
        )


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


def _recall_service(
    *,
    entities: PostgresEntityRepository,
    queries: PostgresMemoryQueryRepository,
) -> StructuredRecallService:
    return StructuredRecallService(
        entity_resolver=DeterministicEntityResolver(entities),
        memory_query_repository=queries,
        clock=FixedClock(NOW),
    )


def _recall_request(
    *,
    subject: str,
    kind: MemoryKind,
    predicate: str,
    mode: RecallMode,
    user_id: str = USER_ID,
    limit: int = 20,
) -> StructuredRecallRequest:
    return StructuredRecallRequest(
        user_id=user_id,
        subject=subject,
        kind=kind,
        predicate=predicate,
        mode=mode,
        limit=limit,
    )


def _recall_orchestration(
    *,
    requests: tuple[StructuredRecallRequest, ...],
    entities: PostgresEntityRepository,
    queries: PostgresMemoryQueryRepository,
) -> RecallOrchestrationService:
    return RecallOrchestrationService(
        planner=FakeRecallPlanner(
            RecallPlan(outcome=RecallPlanOutcome.PLANNED, requests=requests)
        ),
        structured_recall_service=_recall_service(entities=entities, queries=queries),
    )


def _answer_service(
    *,
    requests: tuple[StructuredRecallRequest, ...],
    entities: PostgresEntityRepository,
    queries: PostgresMemoryQueryRepository,
) -> tuple[RecallAnswerService, FakeAnswerSynthesizer]:
    synthesizer = FakeAnswerSynthesizer()
    return (
        RecallAnswerService(
            recall_orchestration_service=_recall_orchestration(
                requests=requests,
                entities=entities,
                queries=queries,
            ),
            answer_synthesizer=synthesizer,
        ),
        synthesizer,
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


def test_recall_current_locations_after_ingestion_supersession_and_user_isolation(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    captures, entities, memories = ingestion_repositories
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
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingestion.ingest(_capture(100, "I parked at A1."))
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.CURRENT_STATE,
            subject="my car",
            subject_type=EntityType.VEHICLE,
            predicate="parked_at",
            value="B7",
        ),
    )
    latest_capture = _capture(101, "I parked at B7.")
    ingestion.ingest(latest_capture)
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.CURRENT_STATE,
            subject="my passport",
            subject_type=EntityType.OBJECT,
            predicate="located_at",
            value="desk drawer",
        ),
    )
    ingestion.ingest(_capture(102, "My passport is in the desk drawer."))

    foreign_subject = Entity(
        id=_id(10_103),
        user_id=OTHER_USER_ID,
        type=EntityType.VEHICLE,
        canonical_name="my car",
    )
    entities.add(user_id=OTHER_USER_ID, entity=foreign_subject)
    memories.append(
        user_id=OTHER_USER_ID,
        memory=Memory(
            id=_id(10_104),
            user_id=OTHER_USER_ID,
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=foreign_subject.id,
            predicate="parked_at",
            value="FOREIGN",
            observed_at=NOW,
            memory_key=Memory.build_memory_key(foreign_subject.id, "parked_at"),
        ),
    )

    recall = _recall_service(entities=entities, queries=query_repository)
    parking = recall.recall(
        _recall_request(
            subject="my car",
            kind=MemoryKind.CURRENT_STATE,
            predicate="parked_at",
            mode=RecallMode.CURRENT,
        )
    )
    passport = recall.recall(
        _recall_request(
            subject="my passport",
            kind=MemoryKind.CURRENT_STATE,
            predicate="located_at",
            mode=RecallMode.CURRENT,
        )
    )

    assert parking.outcome == RecallOutcome.FOUND
    assert [memory.value for memory in parking.memories] == ["B7"]
    assert parking.memories[0].source_capture_id == latest_capture.id
    assert passport.memories[0].value == "desk drawer"
    assert captures.get(user_id=USER_ID, capture_id=latest_capture.id) == latest_capture
    assert all(memory.user_id == USER_ID for memory in parking.memories)


def test_recall_facts_and_multiple_preferences_from_postgres(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.FACT,
                subject="Kevin",
                subject_type=EntityType.PERSON,
                predicate="birthday",
                value="March 12",
            )
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingestion.ingest(_capture(110, "Kevin's birthday is March 12."))
    extractor.candidates = tuple(
        _candidate(
            kind=MemoryKind.PREFERENCE,
            subject="Kevin",
            subject_type=EntityType.PERSON,
            predicate="likes",
            value=value,
        )
        for value in ("coffee", "jazz")
    )
    ingestion.ingest(_capture(111, "Kevin likes coffee and jazz."))
    recall = _recall_service(entities=entities, queries=query_repository)

    birthday = recall.recall(
        _recall_request(
            subject="Kevin",
            kind=MemoryKind.FACT,
            predicate="birthday",
            mode=RecallMode.CURRENT,
        )
    )
    preferences = recall.recall(
        _recall_request(
            subject="Kevin",
            kind=MemoryKind.PREFERENCE,
            predicate="likes",
            mode=RecallMode.ACTIVE,
        )
    )

    assert [memory.value for memory in birthday.memories] == ["March 12"]
    assert {memory.value for memory in preferences.memories} == {"coffee", "jazz"}


def test_recall_event_history_and_latest_use_effective_event_time(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.EVENT,
                subject="me",
                subject_type=EntityType.PERSON,
                predicate="bench_press",
                value="185x5",
                occurred_at=NOW - timedelta(days=3),
            )
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingestion.ingest(_capture(120, "Bench 185x5 three days ago."))
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.EVENT,
            subject="me",
            subject_type=EntityType.PERSON,
            predicate="bench_press",
            value="190x5",
            occurred_at=NOW - timedelta(days=1),
        ),
    )
    ingestion.ingest(_capture(121, "Bench 190x5 yesterday."))
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.EVENT,
            subject="me",
            subject_type=EntityType.PERSON,
            predicate="oil_changed",
            value={"mileage": 42_000},
            occurred_at=NOW - timedelta(days=2),
        ),
    )
    ingestion.ingest(_capture(122, "Changed oil at 42,000 miles."))
    recall = _recall_service(entities=entities, queries=query_repository)

    history = recall.recall(
        _recall_request(
            subject="me",
            kind=MemoryKind.EVENT,
            predicate="bench_press",
            mode=RecallMode.HISTORY,
        )
    )
    latest_oil = recall.recall(
        _recall_request(
            subject="me",
            kind=MemoryKind.EVENT,
            predicate="oil_changed",
            mode=RecallMode.LATEST,
        )
    )

    assert [memory.value for memory in history.memories] == ["190x5", "185x5"]
    assert latest_oil.memories[0].value == {"mileage": 42_000}


def test_recall_active_intents_and_stale_history_from_postgres(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, memories = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.INTENT,
                subject="me",
                subject_type=EntityType.PERSON,
                predicate="buy",
                value=value,
            )
            for value in ("milk", "eggs", "coffee")
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    result = ingestion.ingest(_capture(130, "Buy milk, eggs, and coffee."))
    completed_id = result.candidate_results[1].memory_id
    cancelled_id = result.candidate_results[2].memory_id
    assert completed_id is not None and cancelled_id is not None
    memories.transition_status(
        user_id=USER_ID,
        memory_id=completed_id,
        expected_status=MemoryStatus.ACTIVE,
        target_status=MemoryStatus.COMPLETED,
    )
    memories.transition_status(
        user_id=USER_ID,
        memory_id=cancelled_id,
        expected_status=MemoryStatus.ACTIVE,
        target_status=MemoryStatus.CANCELLED,
    )
    subject = entities.list_for_user(user_id=USER_ID)[0]
    stale = Memory(
        id=_id(10_131),
        user_id=USER_ID,
        kind=MemoryKind.FACT,
        subject_entity_id=subject.id,
        predicate="temporary_note",
        value="stale",
        observed_at=NOW - timedelta(days=2),
        valid_until=NOW - timedelta(days=1),
    )
    memories.append(user_id=USER_ID, memory=stale)
    recall = _recall_service(entities=entities, queries=query_repository)

    active = recall.recall(
        _recall_request(
            subject="me",
            kind=MemoryKind.INTENT,
            predicate="buy",
            mode=RecallMode.ACTIVE,
        )
    )
    intent_history = recall.recall(
        _recall_request(
            subject="me",
            kind=MemoryKind.INTENT,
            predicate="buy",
            mode=RecallMode.HISTORY,
        )
    )
    stale_current = recall.recall(
        _recall_request(
            subject="me",
            kind=MemoryKind.FACT,
            predicate="temporary_note",
            mode=RecallMode.CURRENT,
        )
    )
    stale_active = recall.recall(
        _recall_request(
            subject="me",
            kind=MemoryKind.FACT,
            predicate="temporary_note",
            mode=RecallMode.ACTIVE,
        )
    )
    stale_history = recall.recall(
        _recall_request(
            subject="me",
            kind=MemoryKind.FACT,
            predicate="temporary_note",
            mode=RecallMode.HISTORY,
        )
    )

    assert [memory.value for memory in active.memories] == ["milk"]
    assert {memory.status for memory in intent_history.memories} == {
        MemoryStatus.ACTIVE,
        MemoryStatus.COMPLETED,
        MemoryStatus.CANCELLED,
    }
    assert stale_current.outcome == RecallOutcome.NOT_FOUND
    assert stale_active.outcome == RecallOutcome.NOT_FOUND
    assert stale_history.memories == (stale,)


def test_recall_orchestration_returns_ordered_current_state_evidence(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.CURRENT_STATE,
                subject="my car",
                subject_type=EntityType.VEHICLE,
                predicate="parked_at",
                value="B7",
            )
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    parking_capture = _capture(200, "I parked at B7.")
    ingestion.ingest(parking_capture)
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.CURRENT_STATE,
            subject="my passport",
            subject_type=EntityType.OBJECT,
            predicate="located_at",
            value="desk drawer",
        ),
    )
    passport_capture = _capture(201, "My passport is in the desk drawer.")
    ingestion.ingest(passport_capture)
    requests = (
        _recall_request(
            subject="my car",
            kind=MemoryKind.CURRENT_STATE,
            predicate="parked_at",
            mode=RecallMode.CURRENT,
        ),
        _recall_request(
            subject="my passport",
            kind=MemoryKind.CURRENT_STATE,
            predicate="located_at",
            mode=RecallMode.CURRENT,
        ),
    )

    result = _recall_orchestration(
        requests=requests,
        entities=entities,
        queries=query_repository,
    ).recall(user_id=USER_ID, question="Where are they?", asked_at=NOW)

    assert result.outcome == RecallExecutionOutcome.FOUND
    assert tuple(execution.request for execution in result.executions) == requests
    assert [memory.value for memory in result.memories] == ["B7", "desk drawer"]
    assert [memory.source_capture_id for memory in result.memories] == [
        parking_capture.id,
        passport_capture.id,
    ]


def test_recall_orchestration_preserves_fact_and_preference_evidence(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.FACT,
                subject="Kevin",
                subject_type=EntityType.PERSON,
                predicate="birthday",
                value="March 12",
            )
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingestion.ingest(_capture(210, "Kevin's birthday is March 12."))
    extractor.candidates = tuple(
        _candidate(
            kind=MemoryKind.PREFERENCE,
            subject="Kevin",
            subject_type=EntityType.PERSON,
            predicate="likes",
            value=value,
        )
        for value in ("coffee", "jazz")
    )
    ingestion.ingest(_capture(211, "Kevin likes coffee and jazz."))
    requests = (
        _recall_request(
            subject="Kevin",
            kind=MemoryKind.FACT,
            predicate="birthday",
            mode=RecallMode.CURRENT,
        ),
        _recall_request(
            subject="Kevin",
            kind=MemoryKind.PREFERENCE,
            predicate="likes",
            mode=RecallMode.ACTIVE,
        ),
    )

    result = _recall_orchestration(
        requests=requests,
        entities=entities,
        queries=query_repository,
    ).recall(user_id=USER_ID, question="What do I know about Kevin?", asked_at=NOW)

    assert result.outcome == RecallExecutionOutcome.FOUND
    assert result.executions[0].result.memories[0].value == "March 12"
    assert {memory.value for memory in result.executions[1].result.memories} == {
        "coffee",
        "jazz",
    }


def test_recall_orchestration_preserves_event_history_and_latest_ordering(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.EVENT,
                subject="me",
                subject_type=EntityType.PERSON,
                predicate="bench_press",
                value="185x5",
                occurred_at=NOW - timedelta(days=3),
            ),
            _candidate(
                kind=MemoryKind.EVENT,
                subject="me",
                subject_type=EntityType.PERSON,
                predicate="oil_changed",
                value={"mileage": 40_000},
                occurred_at=NOW - timedelta(days=30),
            ),
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingestion.ingest(_capture(220, "Bench 185x5 and changed oil at 40,000 miles."))
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.EVENT,
            subject="me",
            subject_type=EntityType.PERSON,
            predicate="bench_press",
            value="190x5",
            occurred_at=NOW - timedelta(days=1),
        ),
        _candidate(
            kind=MemoryKind.EVENT,
            subject="me",
            subject_type=EntityType.PERSON,
            predicate="oil_changed",
            value={"mileage": 42_000},
            occurred_at=NOW - timedelta(days=2),
        ),
    )
    ingestion.ingest(_capture(221, "Bench 190x5 and changed oil at 42,000 miles."))
    requests = (
        _recall_request(
            subject="me",
            kind=MemoryKind.EVENT,
            predicate="bench_press",
            mode=RecallMode.HISTORY,
        ),
        _recall_request(
            subject="me",
            kind=MemoryKind.EVENT,
            predicate="oil_changed",
            mode=RecallMode.LATEST,
        ),
    )

    result = _recall_orchestration(
        requests=requests,
        entities=entities,
        queries=query_repository,
    ).recall(user_id=USER_ID, question="Show my recent events.", asked_at=NOW)

    assert result.outcome == RecallExecutionOutcome.FOUND
    assert [
        memory.value for memory in result.executions[0].result.memories
    ] == ["190x5", "185x5"]
    assert result.executions[1].result.memories[0].value == {"mileage": 42_000}


def test_recall_orchestration_returns_only_active_shopping_intents(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, memories = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.INTENT,
                subject="me",
                subject_type=EntityType.PERSON,
                predicate="buy",
                value=value,
            )
            for value in ("milk", "eggs", "coffee")
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingested = ingestion.ingest(_capture(230, "Buy milk, eggs, and coffee."))
    for candidate, status in zip(
        ingested.candidate_results[1:],
        (MemoryStatus.COMPLETED, MemoryStatus.CANCELLED),
        strict=True,
    ):
        assert candidate.memory_id is not None
        memories.transition_status(
            user_id=USER_ID,
            memory_id=candidate.memory_id,
            expected_status=MemoryStatus.ACTIVE,
            target_status=status,
        )
    request = _recall_request(
        subject="me",
        kind=MemoryKind.INTENT,
        predicate="buy",
        mode=RecallMode.ACTIVE,
    )

    result = _recall_orchestration(
        requests=(request,),
        entities=entities,
        queries=query_repository,
    ).recall(user_id=USER_ID, question="What do I still need to buy?", asked_at=NOW)

    assert result.outcome == RecallExecutionOutcome.FOUND
    assert [memory.value for memory in result.memories] == ["milk"]


def test_recall_orchestration_reports_partial_without_cross_user_evidence(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, memories = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.CURRENT_STATE,
                subject="my car",
                subject_type=EntityType.VEHICLE,
                predicate="parked_at",
                value="C3",
            )
        ]
    )
    _service(extractor=extractor, repositories=ingestion_repositories).ingest(
        _capture(240, "I parked at C3.")
    )
    foreign_subject = Entity(
        id=_id(10_240),
        user_id=OTHER_USER_ID,
        type=EntityType.OBJECT,
        canonical_name="my passport",
    )
    entities.add(user_id=OTHER_USER_ID, entity=foreign_subject)
    memories.append(
        user_id=OTHER_USER_ID,
        memory=Memory(
            id=_id(10_241),
            user_id=OTHER_USER_ID,
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=foreign_subject.id,
            predicate="located_at",
            value="FOREIGN",
            observed_at=NOW,
            memory_key=Memory.build_memory_key(foreign_subject.id, "located_at"),
        ),
    )
    requests = (
        _recall_request(
            subject="my car",
            kind=MemoryKind.CURRENT_STATE,
            predicate="parked_at",
            mode=RecallMode.CURRENT,
        ),
        _recall_request(
            subject="my passport",
            kind=MemoryKind.CURRENT_STATE,
            predicate="located_at",
            mode=RecallMode.CURRENT,
        ),
    )

    result = _recall_orchestration(
        requests=requests,
        entities=entities,
        queries=query_repository,
    ).recall(user_id=USER_ID, question="Where are my things?", asked_at=NOW)

    assert result.outcome == RecallExecutionOutcome.PARTIAL
    assert [execution.result.outcome for execution in result.executions] == [
        RecallOutcome.FOUND,
        RecallOutcome.NOT_FOUND,
    ]
    assert [memory.value for memory in result.memories] == ["C3"]
    assert all(memory.user_id == USER_ID for memory in result.memories)

    missing_result = _recall_orchestration(
        requests=(requests[1],),
        entities=entities,
        queries=query_repository,
    ).recall(user_id=USER_ID, question="Where is my passport?", asked_at=NOW)

    assert missing_result.outcome == RecallExecutionOutcome.NOT_FOUND
    assert missing_result.memories == ()


def test_answer_path_returns_cited_parking_evidence_with_provenance_and_isolation(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, memories = ingestion_repositories
    capture = _capture(300, "I parked at D5.")
    _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    kind=MemoryKind.CURRENT_STATE,
                    subject="my car",
                    subject_type=EntityType.VEHICLE,
                    predicate="parked_at",
                    value="D5",
                )
            ]
        ),
        repositories=ingestion_repositories,
    ).ingest(capture)
    foreign_subject = Entity(
        id=_id(10_300),
        user_id=OTHER_USER_ID,
        type=EntityType.VEHICLE,
        canonical_name="my car",
    )
    entities.add(user_id=OTHER_USER_ID, entity=foreign_subject)
    memories.append(
        user_id=OTHER_USER_ID,
        memory=Memory(
            id=_id(10_301),
            user_id=OTHER_USER_ID,
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=foreign_subject.id,
            predicate="parked_at",
            value="FOREIGN",
            observed_at=NOW,
            memory_key=Memory.build_memory_key(foreign_subject.id, "parked_at"),
        ),
    )
    request = _recall_request(
        subject="my car",
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        mode=RecallMode.CURRENT,
    )
    answer_service, synthesizer = _answer_service(
        requests=(request,),
        entities=entities,
        queries=query_repository,
    )

    result = answer_service.answer(
        user_id=USER_ID,
        question="Where did I park?",
        asked_at=NOW,
    )

    assert result.outcome == RecallAnswerOutcome.ANSWERED
    assert [memory.value for memory in result.evidence] == ["D5"]
    assert result.evidence[0].source_capture_id == capture.id
    assert result.cited_memory_ids == (result.evidence[0].id,)
    assert synthesizer.calls[0][1] == result.evidence
    assert all(memory.user_id == USER_ID for memory in synthesizer.calls[0][1])


def test_answer_path_preserves_multiple_fact_values_and_preferences(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.FACT,
                subject="Kevin",
                subject_type=EntityType.PERSON,
                predicate="birthday",
                value="March 12",
            )
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingestion.ingest(_capture(310, "Kevin's birthday is March 12."))
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.FACT,
            subject="Kevin",
            subject_type=EntityType.PERSON,
            predicate="birthday",
            value="March 13",
        ),
    )
    ingestion.ingest(_capture(311, "Kevin's birthday is March 13."))
    extractor.candidates = tuple(
        _candidate(
            kind=MemoryKind.PREFERENCE,
            subject="Kevin",
            subject_type=EntityType.PERSON,
            predicate="likes",
            value=value,
        )
        for value in ("coffee", "jazz")
    )
    ingestion.ingest(_capture(312, "Kevin likes coffee and jazz."))
    extractor.candidates = tuple(
        _candidate(
            kind=MemoryKind.FACT,
            subject="Kevin",
            subject_type=EntityType.PERSON,
            predicate="phone_number",
            value=value,
        )
        for value in ("555-1111", "555-2222")
    )
    ingestion.ingest(_capture(313, "Kevin's numbers are 555-1111 and 555-2222."))
    requests = (
        _recall_request(
            subject="Kevin",
            kind=MemoryKind.FACT,
            predicate="birthday",
            mode=RecallMode.CURRENT,
        ),
        _recall_request(
            subject="Kevin",
            kind=MemoryKind.PREFERENCE,
            predicate="likes",
            mode=RecallMode.ACTIVE,
        ),
        _recall_request(
            subject="Kevin",
            kind=MemoryKind.FACT,
            predicate="phone_number",
            mode=RecallMode.CURRENT,
        ),
    )
    answer_service, synthesizer = _answer_service(
        requests=requests,
        entities=entities,
        queries=query_repository,
    )

    result = answer_service.answer(
        user_id=USER_ID,
        question="What birthdays, preferences, and phone numbers are saved for Kevin?",
        asked_at=NOW,
    )

    assert result.outcome == RecallAnswerOutcome.ANSWERED
    assert {memory.value for memory in result.evidence} == {
        "March 12",
        "March 13",
        "coffee",
        "jazz",
        "555-1111",
        "555-2222",
    }
    assert result.cited_memory_ids == tuple(memory.id for memory in result.evidence)
    assert synthesizer.calls[0][1] == result.evidence


def test_answer_path_passes_latest_oil_change_and_only_active_intents(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, memories = ingestion_repositories
    extractor = FakeExtractor(
        [
            _candidate(
                kind=MemoryKind.EVENT,
                subject="my vehicle",
                subject_type=EntityType.VEHICLE,
                predicate="oil_changed",
                value={"mileage": 40_000},
                occurred_at=NOW - timedelta(days=30),
            )
        ]
    )
    ingestion = _service(extractor=extractor, repositories=ingestion_repositories)
    ingestion.ingest(_capture(320, "Changed oil at 40,000 miles."))
    extractor.candidates = (
        _candidate(
            kind=MemoryKind.EVENT,
            subject="my vehicle",
            subject_type=EntityType.VEHICLE,
            predicate="oil_changed",
            value={"mileage": 42_000},
            occurred_at=NOW - timedelta(days=2),
        ),
    )
    ingestion.ingest(_capture(321, "Changed oil at 42,000 miles."))
    extractor.candidates = tuple(
        _candidate(
            kind=MemoryKind.INTENT,
            subject="me",
            subject_type=EntityType.PERSON,
            predicate="buy",
            value=value,
        )
        for value in ("milk", "eggs", "coffee")
    )
    intent_result = ingestion.ingest(_capture(322, "Buy milk, eggs, and coffee."))
    for candidate, status in zip(
        intent_result.candidate_results[1:],
        (MemoryStatus.COMPLETED, MemoryStatus.CANCELLED),
        strict=True,
    ):
        assert candidate.memory_id is not None
        memories.transition_status(
            user_id=USER_ID,
            memory_id=candidate.memory_id,
            expected_status=MemoryStatus.ACTIVE,
            target_status=status,
        )
    requests = (
        _recall_request(
            subject="my vehicle",
            kind=MemoryKind.EVENT,
            predicate="oil_changed",
            mode=RecallMode.LATEST,
        ),
        _recall_request(
            subject="me",
            kind=MemoryKind.INTENT,
            predicate="buy",
            mode=RecallMode.ACTIVE,
        ),
    )
    answer_service, synthesizer = _answer_service(
        requests=requests,
        entities=entities,
        queries=query_repository,
    )

    result = answer_service.answer(
        user_id=USER_ID,
        question="When was my latest oil change and what should I buy?",
        asked_at=NOW,
    )

    assert result.outcome == RecallAnswerOutcome.ANSWERED
    assert [memory.value for memory in result.evidence] == [
        {"mileage": 42_000},
        "milk",
    ]
    assert synthesizer.calls[0][1] == result.evidence


def test_answer_path_missing_subject_bypasses_synthesizer(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    request = _recall_request(
        subject="my passport",
        kind=MemoryKind.CURRENT_STATE,
        predicate="located_at",
        mode=RecallMode.CURRENT,
    )
    answer_service, synthesizer = _answer_service(
        requests=(request,),
        entities=entities,
        queries=query_repository,
    )

    result = answer_service.answer(
        user_id=USER_ID,
        question="Where is my passport?",
        asked_at=NOW,
    )

    assert result.outcome == RecallAnswerOutcome.NOT_FOUND
    assert result.text == NO_EVIDENCE_MESSAGE
    assert result.evidence == ()
    assert synthesizer.calls == []


def test_answer_path_partial_recall_stays_partial_and_synthesizes_only_hit(
    ingestion_repositories: tuple[
        PostgresCaptureRepository,
        PostgresEntityRepository,
        PostgresMemoryRepository,
    ],
    query_repository: PostgresMemoryQueryRepository,
) -> None:
    _, entities, _ = ingestion_repositories
    _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    kind=MemoryKind.CURRENT_STATE,
                    subject="my car",
                    subject_type=EntityType.VEHICLE,
                    predicate="parked_at",
                    value="E8",
                )
            ]
        ),
        repositories=ingestion_repositories,
    ).ingest(_capture(330, "I parked at E8."))
    requests = (
        _recall_request(
            subject="my car",
            kind=MemoryKind.CURRENT_STATE,
            predicate="parked_at",
            mode=RecallMode.CURRENT,
        ),
        _recall_request(
            subject="my passport",
            kind=MemoryKind.CURRENT_STATE,
            predicate="located_at",
            mode=RecallMode.CURRENT,
        ),
    )
    answer_service, synthesizer = _answer_service(
        requests=requests,
        entities=entities,
        queries=query_repository,
    )

    result = answer_service.answer(
        user_id=USER_ID,
        question="Where are my car and passport?",
        asked_at=NOW,
    )

    assert result.outcome == RecallAnswerOutcome.PARTIAL
    assert [execution.result.outcome for execution in result.recall_result.executions] == [
        RecallOutcome.FOUND,
        RecallOutcome.NOT_FOUND,
    ]
    assert [memory.value for memory in result.evidence] == ["E8"]
    assert synthesizer.calls[0][1] == result.evidence
