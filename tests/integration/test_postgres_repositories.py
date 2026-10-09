"""Repository contract tests against a real PostgreSQL instance."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mnemo.interfaces.repositories import RepositoryInvariantError
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.persistence.postgres.mapping import memory_to_row
from mnemo.persistence.postgres.repositories import (
    PostgresCaptureRepository,
    PostgresEntityRepository,
    PostgresMemoryRepository,
)
from mnemo.persistence.postgres.session import create_postgres_engine, create_session_factory

pytestmark = pytest.mark.postgres

USER_ID = "postgres-user"
OTHER_USER_ID = "other-postgres-user"
NOW = datetime(2026, 10, 8, 15, 30, tzinfo=UTC)
ROOT = Path(__file__).parents[2]


def _id(number: int) -> UUID:
    return UUID(int=number)


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
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
def clean_database(postgres_engine: Engine) -> Iterator[None]:
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE memories, captures, entities CASCADE"))
    yield


@pytest.fixture
def session_factory(postgres_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(postgres_engine)


@pytest.fixture
def repositories(
    session_factory: sessionmaker[Session],
) -> tuple[PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository]:
    return (
        PostgresCaptureRepository(session_factory),
        PostgresEntityRepository(session_factory),
        PostgresMemoryRepository(session_factory),
    )


def _capture(number: int, *, user_id: str = USER_ID, raw_text: str = "capture") -> Capture:
    return Capture(
        id=_id(number),
        user_id=user_id,
        source_type=SourceType.VOICE,
        raw_text=raw_text,
        captured_at=NOW,
        created_at=NOW + timedelta(seconds=1),
    )


def _entity(
    number: int,
    *,
    user_id: str = USER_ID,
    name: str = "Subject",
    aliases: tuple[str, ...] = (),
) -> Entity:
    return Entity(
        id=_id(number),
        user_id=user_id,
        type=EntityType.PERSON,
        canonical_name=name,
        aliases=list(aliases),
    )


def _memory(
    number: int,
    *,
    subject_entity_id: UUID,
    user_id: str = USER_ID,
    kind: MemoryKind = MemoryKind.EVENT,
    predicate: str = "recorded",
    value: object = "value",
    object_entity_id: UUID | None = None,
    source_capture_id: UUID | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    superseded_by_id: UUID | None = None,
) -> Memory:
    memory_key = (
        Memory.build_memory_key(subject_entity_id, predicate)
        if kind == MemoryKind.CURRENT_STATE
        else None
    )
    return Memory(
        id=_id(number),
        user_id=user_id,
        kind=kind,
        category="integration",
        subject_entity_id=subject_entity_id,
        predicate=predicate,
        object_entity_id=object_entity_id,
        value=value,
        observed_at=NOW,
        occurred_at=NOW - timedelta(days=1),
        valid_from=NOW - timedelta(days=2),
        valid_until=NOW + timedelta(days=2),
        expires_at=NOW + timedelta(days=3),
        status=status,
        confidence=0.875,
        memory_key=memory_key,
        superseded_by_id=superseded_by_id,
        source_capture_id=source_capture_id,
        created_at=NOW + timedelta(seconds=2),
        updated_at=NOW + timedelta(seconds=3),
    )


def test_migration_is_at_head_and_installs_required_indexes(postgres_engine: Engine) -> None:
    with postgres_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
        index_definition = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND indexname = 'uq_memories_active_current_state_slot'"
            )
        )
        recall_index = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND indexname = 'ix_memories_structured_recall'"
            )
        )

    assert revision == "20261009_0002"
    assert index_definition is not None
    assert "UNIQUE INDEX" in index_definition
    assert "WHERE" in index_definition
    assert "CURRENT_STATE" in index_definition
    assert "ACTIVE" in index_definition
    assert recall_index is not None
    assert "user_id, subject_entity_id, kind, status, predicate" in recall_index


def test_capture_round_trip_scope_duplicates_and_exact_provenance(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    captures, _, _ = repositories
    capture = _capture(1, raw_text="  I parked at A1.\n")
    captures.add(user_id=USER_ID, capture=capture)

    loaded = captures.get(user_id=USER_ID, capture_id=capture.id)
    assert loaded == capture
    assert loaded is not None
    assert loaded.raw_text == "  I parked at A1.\n"
    assert loaded.captured_at.tzinfo is not None
    assert loaded.created_at.tzinfo is not None
    assert captures.get(user_id=OTHER_USER_ID, capture_id=capture.id) is None

    with pytest.raises(RepositoryInvariantError):
        captures.add(user_id=OTHER_USER_ID, capture=_capture(2))
    with pytest.raises(RepositoryInvariantError):
        captures.add(user_id=USER_ID, capture=capture)


def test_entity_round_trip_scope_duplicates_and_aliases(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    _, entities, _ = repositories
    own = _entity(10, name="Kevin Wang", aliases=("Kevin", "K.W."))
    foreign = _entity(11, user_id=OTHER_USER_ID, name="Kevin")
    entities.add(user_id=USER_ID, entity=own)
    entities.add(user_id=OTHER_USER_ID, entity=foreign)

    loaded = entities.get(user_id=USER_ID, entity_id=own.id)
    assert loaded == own
    assert loaded is not None
    assert entities.get(user_id=OTHER_USER_ID, entity_id=own.id) is None
    assert loaded.aliases == ["Kevin", "K.W."]
    assert tuple(entities.list_for_user(user_id=USER_ID)) == (own,)
    assert tuple(entities.list_for_user(user_id=OTHER_USER_ID)) == (foreign,)

    with pytest.raises(RepositoryInvariantError):
        entities.add(user_id=USER_ID, entity=_entity(12, user_id=OTHER_USER_ID))
    with pytest.raises(RepositoryInvariantError):
        entities.add(user_id=USER_ID, entity=own)


def test_memory_round_trip_json_filters_scope_and_provenance(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    captures, entities, memories = repositories
    source = _capture(20)
    subject = _entity(21, name="My car")
    object_entity = _entity(22, name="Garage")
    captures.add(user_id=USER_ID, capture=source)
    entities.add(user_id=USER_ID, entity=subject)
    entities.add(user_id=USER_ID, entity=object_entity)
    memory = _memory(
        23,
        subject_entity_id=subject.id,
        predicate="oil_changed",
        value={"mileage": 42_800, "unit": "mile", "details": [True, None]},
        object_entity_id=object_entity.id,
        source_capture_id=source.id,
    )
    memories.append(user_id=USER_ID, memory=memory)

    loaded = memories.get(user_id=USER_ID, memory_id=memory.id)
    assert loaded == memory
    assert loaded is not None
    assert loaded.value == {"mileage": 42_800, "unit": "mile", "details": [True, None]}
    assert loaded.source_capture_id == source.id
    assert loaded.object_entity_id == object_entity.id
    assert loaded.observed_at.tzinfo is not None
    assert memories.get(user_id=OTHER_USER_ID, memory_id=memory.id) is None
    assert tuple(
        memories.list_active(
            user_id=USER_ID,
            kind=MemoryKind.EVENT,
            subject_entity_id=subject.id,
            predicate="oil_changed",
        )
    ) == (memory,)
    assert memories.list_active(user_id=USER_ID, kind=MemoryKind.INTENT) == ()


def test_memory_append_rejects_scope_duplicate_and_missing_references(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    _, entities, memories = repositories
    subject = _entity(30)
    entities.add(user_id=USER_ID, entity=subject)
    memory = _memory(31, subject_entity_id=subject.id)
    memories.append(user_id=USER_ID, memory=memory)

    with pytest.raises(RepositoryInvariantError):
        memories.append(user_id=OTHER_USER_ID, memory=_memory(32, subject_entity_id=subject.id))
    with pytest.raises(RepositoryInvariantError):
        memories.append(user_id=USER_ID, memory=memory)
    with pytest.raises(RepositoryInvariantError):
        memories.append(user_id=USER_ID, memory=_memory(33, subject_entity_id=_id(999)))


def test_current_state_supersession_is_atomic_and_preserves_history(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    captures, entities, memories = repositories
    source = _capture(40)
    subject = _entity(41, name="My car")
    captures.add(user_id=USER_ID, capture=source)
    entities.add(user_id=USER_ID, entity=subject)
    current = _memory(
        42,
        subject_entity_id=subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        value="A1",
        source_capture_id=source.id,
    )
    incoming = _memory(
        43,
        subject_entity_id=subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        value="B7",
        source_capture_id=source.id,
    )
    memories.append(user_id=USER_ID, memory=current)

    memories.supersede_current_state(
        user_id=USER_ID,
        current_memory_id=current.id,
        incoming=incoming,
    )

    historical = memories.get(user_id=USER_ID, memory_id=current.id)
    assert historical == current.model_copy(
        update={"status": MemoryStatus.SUPERSEDED, "superseded_by_id": incoming.id}
    )
    assert memories.get(user_id=USER_ID, memory_id=incoming.id) == incoming
    assert tuple(
        memories.list_active(user_id=USER_ID, memory_key=current.memory_key)
    ) == (incoming,)


def test_invalid_supersessions_roll_back_without_partial_mutation(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    _, entities, memories = repositories
    subject = _entity(50)
    other_subject = _entity(51)
    foreign_subject = _entity(52, user_id=OTHER_USER_ID)
    entities.add(user_id=USER_ID, entity=subject)
    entities.add(user_id=USER_ID, entity=other_subject)
    entities.add(user_id=OTHER_USER_ID, entity=foreign_subject)
    current = _memory(
        53,
        subject_entity_id=subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
    )
    memories.append(user_id=USER_ID, memory=current)

    wrong_slot = _memory(
        54,
        subject_entity_id=other_subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="located_at",
    )
    with pytest.raises(RepositoryInvariantError):
        memories.supersede_current_state(
            user_id=USER_ID,
            current_memory_id=current.id,
            incoming=wrong_slot,
        )
    assert memories.get(user_id=USER_ID, memory_id=current.id) == current
    assert memories.get(user_id=USER_ID, memory_id=wrong_slot.id) is None

    foreign = _memory(
        55,
        user_id=OTHER_USER_ID,
        subject_entity_id=foreign_subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
    )
    with pytest.raises(RepositoryInvariantError):
        memories.supersede_current_state(
            user_id=USER_ID,
            current_memory_id=current.id,
            incoming=foreign,
        )
    assert memories.get(user_id=USER_ID, memory_id=current.id) == current

    occupied_id = _memory(56, subject_entity_id=subject.id)
    memories.append(user_id=USER_ID, memory=occupied_id)
    duplicate_id = _memory(
        56,
        subject_entity_id=subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
    )
    with pytest.raises(RepositoryInvariantError):
        memories.supersede_current_state(
            user_id=USER_ID,
            current_memory_id=current.id,
            incoming=duplicate_id,
        )
    assert memories.get(user_id=USER_ID, memory_id=current.id) == current
    assert memories.get(user_id=USER_ID, memory_id=occupied_id.id) == occupied_id


def test_database_rejects_a_second_active_current_state_directly(
    session_factory: sessionmaker[Session],
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    _, entities, memories = repositories
    subject = _entity(60)
    entities.add(user_id=USER_ID, entity=subject)
    first = _memory(
        61,
        subject_entity_id=subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        value="A1",
    )
    conflicting = _memory(
        62,
        subject_entity_id=subject.id,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        value="B7",
    )
    memories.append(user_id=USER_ID, memory=first)

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(memory_to_row(conflicting))

    assert memories.get(user_id=USER_ID, memory_id=first.id) == first
    assert memories.get(user_id=USER_ID, memory_id=conflicting.id) is None


def test_status_transition_is_atomic_and_preserves_unrelated_fields(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    captures, entities, memories = repositories
    source = _capture(70)
    subject = _entity(71)
    captures.add(user_id=USER_ID, capture=source)
    entities.add(user_id=USER_ID, entity=subject)
    intent = _memory(
        72,
        subject_entity_id=subject.id,
        kind=MemoryKind.INTENT,
        predicate="buy",
        value={"item": "AirPods"},
        source_capture_id=source.id,
    )
    memories.append(user_id=USER_ID, memory=intent)

    memories.transition_status(
        user_id=USER_ID,
        memory_id=intent.id,
        expected_status=MemoryStatus.ACTIVE,
        target_status=MemoryStatus.COMPLETED,
    )
    completed = intent.model_copy(update={"status": MemoryStatus.COMPLETED})
    assert memories.get(user_id=USER_ID, memory_id=intent.id) == completed

    with pytest.raises(RepositoryInvariantError):
        memories.transition_status(
            user_id=USER_ID,
            memory_id=intent.id,
            expected_status=MemoryStatus.ACTIVE,
            target_status=MemoryStatus.CANCELLED,
        )
    with pytest.raises(RepositoryInvariantError, match="replacement-aware"):
        memories.transition_status(
            user_id=USER_ID,
            memory_id=intent.id,
            expected_status=MemoryStatus.COMPLETED,
            target_status=MemoryStatus.SUPERSEDED,
        )
    with pytest.raises(RepositoryInvariantError):
        memories.transition_status(
            user_id=OTHER_USER_ID,
            memory_id=intent.id,
            expected_status=MemoryStatus.COMPLETED,
            target_status=MemoryStatus.CANCELLED,
        )
    assert memories.get(user_id=USER_ID, memory_id=intent.id) == completed


@pytest.mark.parametrize("reference_kind", ["subject", "object", "capture", "superseded"])
def test_cross_user_references_are_rejected_by_postgres(
    reference_kind: str,
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    captures, entities, memories = repositories
    own_subject = _entity(80)
    foreign_entity = _entity(81, user_id=OTHER_USER_ID)
    foreign_capture = _capture(82, user_id=OTHER_USER_ID)
    entities.add(user_id=USER_ID, entity=own_subject)
    entities.add(user_id=OTHER_USER_ID, entity=foreign_entity)
    captures.add(user_id=OTHER_USER_ID, capture=foreign_capture)
    foreign_memory = _memory(
        83,
        user_id=OTHER_USER_ID,
        subject_entity_id=foreign_entity.id,
    )
    memories.append(user_id=OTHER_USER_ID, memory=foreign_memory)

    if reference_kind == "subject":
        incoming = _memory(84, subject_entity_id=foreign_entity.id)
    elif reference_kind == "object":
        incoming = _memory(
            84,
            subject_entity_id=own_subject.id,
            object_entity_id=foreign_entity.id,
        )
    elif reference_kind == "capture":
        incoming = _memory(
            84,
            subject_entity_id=own_subject.id,
            source_capture_id=foreign_capture.id,
        )
    else:
        incoming = _memory(
            84,
            subject_entity_id=own_subject.id,
            status=MemoryStatus.SUPERSEDED,
            superseded_by_id=foreign_memory.id,
        )

    with pytest.raises(RepositoryInvariantError):
        memories.append(user_id=USER_ID, memory=incoming)

    assert memories.get(user_id=USER_ID, memory_id=incoming.id) is None


def test_active_list_excludes_terminal_memories(
    repositories: tuple[
        PostgresCaptureRepository, PostgresEntityRepository, PostgresMemoryRepository
    ],
) -> None:
    _, entities, memories = repositories
    subject = _entity(90)
    entities.add(user_id=USER_ID, entity=subject)
    active = _memory(91, subject_entity_id=subject.id)
    expired = _memory(
        92,
        subject_entity_id=subject.id,
        status=MemoryStatus.EXPIRED,
    )
    memories.append(user_id=USER_ID, memory=active)
    memories.append(user_id=USER_ID, memory=expired)

    listed = memories.list_active(user_id=USER_ID)

    assert listed == (active,)
