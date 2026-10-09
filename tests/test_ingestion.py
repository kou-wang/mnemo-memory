"""Fast orchestration tests using provider- and database-free fakes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from mnemo.entities import DeterministicEntityResolver
from mnemo.ingestion import (
    CandidateIngestionOutcome,
    CandidateIngestionResult,
    EntityMentionRole,
    IngestionInvariantError,
    IngestionService,
)
from mnemo.interfaces.entities import EntityResolution, EntityResolutionOutcome
from mnemo.interfaces.repositories import RepositoryInvariantError
from mnemo.lifecycle.engine import LifecycleAction, LifecycleDecision, LifecycleEngine
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
USER_ID = "ingestion-user"


def _id(number: int) -> UUID:
    return UUID(int=number)


class FakeCaptureRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Capture] = {}
        self.add_count = 0

    def add(self, *, user_id: str, capture: Capture) -> None:
        if capture.user_id != user_id or capture.id in self.items:
            raise RepositoryInvariantError("invalid capture add")
        self.items[capture.id] = capture
        self.add_count += 1

    def get(self, *, user_id: str, capture_id: UUID) -> Capture | None:
        capture = self.items.get(capture_id)
        return capture if capture is not None and capture.user_id == user_id else None


class FakeEntityRepository:
    def __init__(self, entities: Sequence[Entity] = ()) -> None:
        self.items = {entity.id: entity for entity in entities}
        self.added: list[Entity] = []

    def add(self, *, user_id: str, entity: Entity) -> None:
        if entity.user_id != user_id or entity.id in self.items:
            raise RepositoryInvariantError("invalid entity add")
        self.items[entity.id] = entity
        self.added.append(entity)

    def get(self, *, user_id: str, entity_id: UUID) -> Entity | None:
        entity = self.items.get(entity_id)
        return entity if entity is not None and entity.user_id == user_id else None

    def list_for_user(self, *, user_id: str) -> Sequence[Entity]:
        return tuple(entity for entity in self.items.values() if entity.user_id == user_id)


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Memory] = {}
        self.writes: list[str] = []

    def list_active(
        self,
        *,
        user_id: str,
        kind: MemoryKind | None = None,
        subject_entity_id: UUID | None = None,
        predicate: str | None = None,
        memory_key: str | None = None,
    ) -> Sequence[Memory]:
        return tuple(
            memory
            for memory in self.items.values()
            if memory.user_id == user_id
            and memory.status == MemoryStatus.ACTIVE
            and (kind is None or memory.kind == kind)
            and (subject_entity_id is None or memory.subject_entity_id == subject_entity_id)
            and (predicate is None or memory.predicate == predicate)
            and (memory_key is None or memory.memory_key == memory_key)
        )

    def get(self, *, user_id: str, memory_id: UUID) -> Memory | None:
        memory = self.items.get(memory_id)
        return memory if memory is not None and memory.user_id == user_id else None

    def append(self, *, user_id: str, memory: Memory) -> None:
        if memory.user_id != user_id or memory.id in self.items:
            raise RepositoryInvariantError("invalid memory append")
        self.items[memory.id] = memory
        self.writes.append("append")

    def supersede_current_state(
        self,
        *,
        user_id: str,
        current_memory_id: UUID,
        incoming: Memory,
    ) -> None:
        current = self.items[current_memory_id]
        if current.user_id != user_id or incoming.user_id != user_id:
            raise RepositoryInvariantError("invalid supersession")
        self.items[current.id] = current.model_copy(
            update={
                "status": MemoryStatus.SUPERSEDED,
                "superseded_by_id": incoming.id,
            }
        )
        self.items[incoming.id] = incoming
        self.writes.append("supersede_current_state")

    def transition_status(
        self,
        *,
        user_id: str,
        memory_id: UUID,
        expected_status: MemoryStatus,
        target_status: MemoryStatus,
    ) -> None:
        raise AssertionError("ingestion must not call transition_status")


class FakeExtractor:
    def __init__(
        self,
        candidates: Sequence[CandidateMemory] = (),
        *,
        before_return: Callable[[Capture], None] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.candidates = tuple(candidates)
        self.before_return = before_return
        self.error = error
        self.calls = 0

    def extract(self, capture: Capture) -> Sequence[CandidateMemory]:
        self.calls += 1
        if self.before_return is not None:
            self.before_return(capture)
        if self.error is not None:
            raise self.error
        return self.candidates


@dataclass(frozen=True)
class FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


def _capture(number: int = 1, *, text: str = "Kevin's birthday is March 12.") -> Capture:
    return Capture(
        id=_id(number),
        user_id=USER_ID,
        source_type=SourceType.TEXT,
        raw_text=text,
        captured_at=NOW + timedelta(minutes=number),
        created_at=NOW + timedelta(minutes=number),
    )


def _candidate(
    *,
    kind: MemoryKind = MemoryKind.FACT,
    subject: str = "Kevin",
    subject_type: EntityType = EntityType.PERSON,
    predicate: str = "birthday",
    value: object = "March 12",
    object_mention: str | None = None,
    object_type: EntityType | None = None,
    occurred_at: datetime | None = None,
) -> CandidateMemory:
    return CandidateMemory(
        kind=kind,
        category="test",
        subject=subject,
        subject_type=subject_type,
        predicate=predicate,
        object=object_mention,
        object_type=object_type,
        value=value,
        occurred_at=occurred_at,
        valid_from=NOW,
        valid_until=NOW + timedelta(days=1),
        expires_at=NOW + timedelta(days=2),
        confidence=0.8,
        metadata={"ignored": True},
    )


def _entity(
    number: int,
    *,
    name: str = "Kevin",
    entity_type: EntityType = EntityType.PERSON,
    user_id: str = USER_ID,
) -> Entity:
    return Entity(
        id=_id(number),
        user_id=user_id,
        type=entity_type,
        canonical_name=name,
    )


def _service(
    *,
    extractor: FakeExtractor,
    entities: FakeEntityRepository | None = None,
    captures: FakeCaptureRepository | None = None,
    memories: FakeMemoryRepository | None = None,
    lifecycle: LifecycleEngine | None = None,
) -> tuple[
    IngestionService,
    FakeCaptureRepository,
    FakeEntityRepository,
    FakeMemoryRepository,
]:
    capture_repository = captures or FakeCaptureRepository()
    entity_repository = entities or FakeEntityRepository()
    memory_repository = memories or FakeMemoryRepository()
    service = IngestionService(
        extractor=extractor,
        entity_resolver=DeterministicEntityResolver(entity_repository),
        capture_repository=capture_repository,
        entity_repository=entity_repository,
        memory_repository=memory_repository,
        clock=FixedClock(NOW),
        lifecycle_engine=lifecycle or LifecycleEngine(),
    )
    return service, capture_repository, entity_repository, memory_repository


def test_capture_is_persisted_before_extraction_and_zero_candidates_succeeds() -> None:
    captures = FakeCaptureRepository()
    extractor = FakeExtractor(
        before_return=lambda capture: assert_capture_stored(captures, capture)
    )
    service, _, _, memories = _service(extractor=extractor, captures=captures)

    result = service.ingest(_capture())

    assert result.candidate_results == ()
    assert memories.writes == []


def assert_capture_stored(repository: FakeCaptureRepository, capture: Capture) -> None:
    assert repository.get(user_id=capture.user_id, capture_id=capture.id) == capture


def test_extraction_failure_preserves_capture_and_propagates() -> None:
    failure = RuntimeError("provider unavailable")
    service, captures, _, memories = _service(extractor=FakeExtractor(error=failure))
    capture = _capture()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.ingest(capture)

    assert captures.get(user_id=USER_ID, capture_id=capture.id) == capture
    assert memories.writes == []


def test_identical_capture_retry_is_accepted_but_conflicting_content_fails() -> None:
    service, captures, _, _ = _service(extractor=FakeExtractor())
    capture = _capture()

    service.ingest(capture)
    service.ingest(capture)

    assert captures.add_count == 1
    with pytest.raises(IngestionInvariantError, match="different content"):
        service.ingest(capture.model_copy(update={"raw_text": "different"}))


def test_matched_subject_is_reused_and_candidate_maps_with_provenance() -> None:
    kevin = _entity(10)
    candidate = _candidate(occurred_at=NOW - timedelta(days=1))
    service, _, entities, memories = _service(
        extractor=FakeExtractor([candidate]),
        entities=FakeEntityRepository([kevin]),
    )
    capture = _capture()

    result = service.ingest(capture)

    outcome = result.candidate_results[0]
    assert outcome.outcome == CandidateIngestionOutcome.PERSISTED
    assert outcome.memory_id is not None
    memory = memories.items[outcome.memory_id]
    assert entities.added == []
    assert memory.subject_entity_id == kevin.id
    assert memory.object_entity_id is None
    assert memory.memory_key is None
    assert memory.source_capture_id == capture.id
    assert memory.observed_at == capture.captured_at
    assert memory.occurred_at == candidate.occurred_at
    assert memory.valid_from == candidate.valid_from
    assert memory.valid_until == candidate.valid_until
    assert memory.expires_at == candidate.expires_at
    assert memory.created_at == NOW
    assert memory.updated_at == NOW
    assert memory.confidence == candidate.confidence
    assert not hasattr(memory, "metadata")
    assert memories.writes == ["append"]


def test_unmatched_subject_creates_entity_with_extracted_type_and_no_aliases() -> None:
    service, _, entities, memories = _service(
        extractor=FakeExtractor(
            [_candidate(subject="my car", subject_type=EntityType.VEHICLE)]
        )
    )

    result = service.ingest(_capture())

    assert len(entities.added) == 1
    assert entities.added[0].canonical_name == "my car"
    assert entities.added[0].type == EntityType.VEHICLE
    assert entities.added[0].aliases == []
    assert len(memories.items) == 1
    assert result.candidate_results[0].outcome == CandidateIngestionOutcome.PERSISTED


def test_ambiguous_subject_blocks_without_entity_or_memory_write() -> None:
    entities = FakeEntityRepository([_entity(20), _entity(21)])
    service, _, entities, memories = _service(
        extractor=FakeExtractor([_candidate()]),
        entities=entities,
    )

    outcome = service.ingest(_capture()).candidate_results[0]

    assert outcome.outcome == CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY
    assert outcome.blocked_role == EntityMentionRole.SUBJECT
    assert outcome.ambiguous_entity_ids == (_id(20), _id(21))
    assert entities.added == []
    assert memories.writes == []


def test_ambiguous_subject_is_not_disambiguated_by_matching_type() -> None:
    entities = FakeEntityRepository(
        [
            _entity(30, entity_type=EntityType.PERSON),
            _entity(31, entity_type=EntityType.ORGANIZATION),
        ]
    )
    service, _, _, memories = _service(
        extractor=FakeExtractor([_candidate(subject_type=EntityType.PERSON)]),
        entities=entities,
    )

    outcome = service.ingest(_capture()).candidate_results[0]

    assert outcome.outcome == CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY
    assert memories.writes == []


def test_matched_subject_type_conflict_blocks_candidate() -> None:
    entities = FakeEntityRepository([_entity(40, entity_type=EntityType.ORGANIZATION)])
    service, _, entities, memories = _service(
        extractor=FakeExtractor([_candidate(subject_type=EntityType.PERSON)]),
        entities=entities,
    )

    outcome = service.ingest(_capture()).candidate_results[0]

    assert outcome.outcome == CandidateIngestionOutcome.BLOCKED_ENTITY_TYPE_CONFLICT
    assert outcome.blocked_role == EntityMentionRole.SUBJECT
    assert entities.added == []
    assert memories.writes == []


def test_matched_and_unmatched_object_paths_materialize_relationships() -> None:
    kevin = _entity(50)
    acme = _entity(51, name="Acme", entity_type=EntityType.ORGANIZATION)
    matched_entities = FakeEntityRepository([kevin, acme])
    matched_service, _, _, matched_memories = _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    predicate="works_at",
                    value=True,
                    object_mention="Acme",
                    object_type=EntityType.ORGANIZATION,
                )
            ]
        ),
        entities=matched_entities,
    )

    matched_service.ingest(_capture())
    assert next(iter(matched_memories.items.values())).object_entity_id == acme.id
    assert matched_entities.added == []

    unmatched_entities = FakeEntityRepository([kevin])
    unmatched_service, _, unmatched_entities, unmatched_memories = _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    predicate="works_at",
                    value=True,
                    object_mention="Acme",
                    object_type=EntityType.ORGANIZATION,
                )
            ]
        ),
        entities=unmatched_entities,
    )
    unmatched_service.ingest(_capture(2))
    created_object = unmatched_entities.added[0]
    assert created_object.canonical_name == "Acme"
    assert created_object.type == EntityType.ORGANIZATION
    assert next(iter(unmatched_memories.items.values())).object_entity_id == created_object.id


@pytest.mark.parametrize(
    ("object_entities", "expected_outcome"),
    [
        (
            [
                _entity(61, name="Acme", entity_type=EntityType.ORGANIZATION),
                _entity(62, name="Acme", entity_type=EntityType.OTHER),
            ],
            CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY,
        ),
        (
            [_entity(63, name="Acme", entity_type=EntityType.PLACE)],
            CandidateIngestionOutcome.BLOCKED_ENTITY_TYPE_CONFLICT,
        ),
    ],
)
def test_blocked_object_prevents_unmatched_subject_creation(
    object_entities: list[Entity],
    expected_outcome: CandidateIngestionOutcome,
) -> None:
    entities = FakeEntityRepository(object_entities)
    service, _, entities, memories = _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    subject="New Person",
                    predicate="works_at",
                    value=True,
                    object_mention="Acme",
                    object_type=EntityType.ORGANIZATION,
                )
            ]
        ),
        entities=entities,
    )

    outcome = service.ingest(_capture()).candidate_results[0]

    assert outcome.outcome == expected_outcome
    assert outcome.blocked_role == EntityMentionRole.OBJECT
    assert entities.added == []
    assert memories.writes == []


def test_same_unmatched_subject_and_object_creates_one_entity() -> None:
    service, _, entities, memories = _service(
        extractor=FakeExtractor(
            [
                _candidate(
                    subject="Alex",
                    predicate="self_reference",
                    value=True,
                    object_mention="  alex  ",
                    object_type=EntityType.PERSON,
                )
            ]
        )
    )

    service.ingest(_capture())

    assert len(entities.added) == 1
    memory = next(iter(memories.items.values()))
    assert memory.subject_entity_id == memory.object_entity_id


def test_current_state_uses_canonical_key_and_atomic_supersession_only() -> None:
    candidate = _candidate(
        kind=MemoryKind.CURRENT_STATE,
        subject="my car",
        subject_type=EntityType.VEHICLE,
        predicate="parked_at",
        value="A1",
    )
    extractor = FakeExtractor([candidate])
    service, _, _, memories = _service(extractor=extractor)

    first = service.ingest(_capture(1)).candidate_results[0]
    assert first.memory_id is not None
    original = memories.items[first.memory_id]
    assert original.memory_key == Memory.build_memory_key(
        original.subject_entity_id,
        "parked_at",
    )

    retry = service.ingest(_capture(1)).candidate_results[0]
    assert retry.outcome == CandidateIngestionOutcome.NOOP
    assert memories.writes == ["append"]

    extractor.candidates = (
        candidate.model_copy(update={"value": "B7"}),
    )
    changed = service.ingest(_capture(2, text="I parked at B7.")).candidate_results[0]
    assert changed.outcome == CandidateIngestionOutcome.PERSISTED
    assert memories.writes == ["append", "supersede_current_state"]
    assert memories.items[original.id].status == MemoryStatus.SUPERSEDED
    assert memories.items[original.id].superseded_by_id == changed.memory_id


def test_exact_duplicate_event_retry_is_noop_without_memory_write() -> None:
    candidate = _candidate(
        kind=MemoryKind.EVENT,
        subject="me",
        predicate="bench_press",
        value={"weight_lb": 185, "reps": 5},
        occurred_at=NOW - timedelta(hours=1),
    )
    service, captures, entities, memories = _service(extractor=FakeExtractor([candidate]))
    capture = _capture()

    first = service.ingest(capture).candidate_results[0]
    retry = service.ingest(capture).candidate_results[0]

    assert first.outcome == CandidateIngestionOutcome.PERSISTED
    assert retry.outcome == CandidateIngestionOutcome.NOOP
    assert captures.add_count == 1
    assert len(entities.added) == 1
    assert memories.writes == ["append"]


class FailingMemoryRepository(FakeMemoryRepository):
    def append(self, *, user_id: str, memory: Memory) -> None:
        raise RuntimeError("database unavailable")


def test_committed_capture_and_entity_remain_after_later_memory_failure() -> None:
    memories = FailingMemoryRepository()
    service, captures, entities, _ = _service(
        extractor=FakeExtractor([_candidate()]),
        memories=memories,
    )
    capture = _capture()

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.ingest(capture)

    assert captures.get(user_id=USER_ID, capture_id=capture.id) == capture
    assert len(entities.added) == 1
    assert memories.items == {}


class ImpossibleLifecycleEngine(LifecycleEngine):
    def reconcile(
        self,
        *,
        existing_active: list[Memory],
        incoming: Memory,
    ) -> LifecycleDecision:
        return LifecycleDecision(
            action=LifecycleAction.APPEND,
            supersede_ids=[_id(999)],
            reason="invalid",
        )


def test_impossible_lifecycle_decision_fails_closed() -> None:
    service, _, _, memories = _service(
        extractor=FakeExtractor([_candidate()]),
        lifecycle=ImpossibleLifecycleEngine(),
    )

    with pytest.raises(IngestionInvariantError, match="impossible supersession"):
        service.ingest(_capture())

    assert memories.writes == []


class ForeignScopeResolver:
    def resolve(self, *, user_id: str, mention: str) -> EntityResolution:
        return EntityResolution(
            user_id="another-user",
            mention=mention,
            outcome=EntityResolutionOutcome.UNMATCHED,
        )


def test_foreign_scope_resolution_fails_closed() -> None:
    extractor = FakeExtractor([_candidate()])
    captures = FakeCaptureRepository()
    entities = FakeEntityRepository()
    memories = FakeMemoryRepository()
    service = IngestionService(
        extractor=extractor,
        entity_resolver=ForeignScopeResolver(),
        capture_repository=captures,
        entity_repository=entities,
        memory_repository=memories,
        clock=FixedClock(NOW),
        lifecycle_engine=LifecycleEngine(),
    )

    with pytest.raises(IngestionInvariantError, match="different user scope"):
        service.ingest(_capture())

    assert entities.added == []
    assert memories.writes == []


@pytest.mark.parametrize(
    "values",
    [
        {
            "outcome": CandidateIngestionOutcome.BLOCKED_ENTITY_TYPE_CONFLICT,
        },
        {
            "outcome": CandidateIngestionOutcome.NOOP,
            "blocked_mention": "Kevin",
            "blocked_role": EntityMentionRole.SUBJECT,
        },
        {
            "outcome": CandidateIngestionOutcome.PERSISTED,
        },
        {
            "outcome": CandidateIngestionOutcome.NOOP,
            "memory_id": _id(700),
        },
        {
            "outcome": CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY,
            "blocked_mention": "Alex",
            "blocked_role": EntityMentionRole.SUBJECT,
            "ambiguous_entity_ids": [_id(701)],
        },
        {
            "outcome": CandidateIngestionOutcome.BLOCKED_ENTITY_TYPE_CONFLICT,
            "blocked_mention": "Kevin",
            "blocked_role": EntityMentionRole.SUBJECT,
            "ambiguous_entity_ids": [_id(702), _id(703)],
        },
    ],
)
def test_candidate_result_rejects_inconsistent_outcome_shapes(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CandidateIngestionResult(candidate_index=0, reason="test", **values)
