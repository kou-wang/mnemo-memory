"""Provider-independent structured recall behavior tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from mnemo.interfaces.entities import EntityResolution, EntityResolutionOutcome
from mnemo.interfaces.queries import MemoryQuery, MemoryQueryOrder
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.recall import (
    RecallInvariantError,
    RecallMode,
    RecallOutcome,
    StructuredRecallRequest,
    StructuredRecallService,
)

NOW = datetime(2026, 10, 9, 18, tzinfo=UTC)
USER_ID = "recall-user"


def _id(number: int) -> UUID:
    return UUID(int=20_000 + number)


@dataclass(frozen=True)
class FixedClock:
    instant: datetime = NOW

    def now(self) -> datetime:
        return self.instant


class StubResolver:
    def __init__(self, resolution: EntityResolution) -> None:
        self.resolution = resolution
        self.calls: list[tuple[str, str]] = []

    def resolve(self, *, user_id: str, mention: str) -> EntityResolution:
        self.calls.append((user_id, mention))
        return self.resolution


class FakeMemoryQueryRepository:
    def __init__(self, memories: Sequence[Memory] = (), *, honor_scope: bool = True) -> None:
        self.memories = tuple(memories)
        self.honor_scope = honor_scope
        self.queries: list[MemoryQuery] = []

    def query(self, query: MemoryQuery) -> Sequence[Memory]:
        self.queries.append(query)
        values = [
            memory
            for memory in self.memories
            if (not self.honor_scope or memory.user_id == query.user_id)
            and (query.statuses is None or memory.status in query.statuses)
            and (query.kind is None or memory.kind == query.kind)
            and (
                query.subject_entity_id is None
                or memory.subject_entity_id == query.subject_entity_id
            )
            and (query.predicate is None or memory.predicate == query.predicate)
            and (
                query.object_entity_id is None
                or memory.object_entity_id == query.object_entity_id
            )
            and _within(memory.occurred_at, query.occurred_at_from, query.occurred_at_until)
            and _within(memory.observed_at, query.observed_at_from, query.observed_at_until)
            and _within(
                memory.occurred_at or memory.observed_at,
                query.event_time_from,
                query.event_time_until,
            )
            and (query.valid_at is None or _valid_at(memory, query.valid_at))
        ]
        if query.order == MemoryQueryOrder.OBSERVED_AT_ASC:
            values.sort(key=lambda memory: (memory.observed_at, memory.id))
        elif query.order == MemoryQueryOrder.OBSERVED_AT_DESC:
            values.sort(key=lambda memory: (memory.observed_at, memory.id), reverse=True)
        else:
            values.sort(
                key=lambda memory: (
                    memory.occurred_at or memory.observed_at,
                    memory.observed_at,
                    memory.id,
                ),
                reverse=True,
            )
        return tuple(values[: query.limit])


def _within(value: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if value is None:
        return start is None and end is None
    return (start is None or value >= start) and (end is None or value <= end)


def _valid_at(memory: Memory, instant: datetime) -> bool:
    return (
        (memory.valid_from is None or memory.valid_from <= instant)
        and (memory.valid_until is None or memory.valid_until >= instant)
        and (memory.expires_at is None or memory.expires_at > instant)
    )


def _entity(
    number: int = 1,
    *,
    name: str = "my car",
    entity_type: EntityType = EntityType.VEHICLE,
) -> Entity:
    return Entity(
        id=_id(number),
        user_id=USER_ID,
        type=entity_type,
        canonical_name=name,
    )


def _resolution(
    outcome: EntityResolutionOutcome = EntityResolutionOutcome.MATCHED,
    *,
    entity: Entity | None = None,
    candidates: tuple[Entity, ...] = (),
) -> EntityResolution:
    return EntityResolution(
        user_id=USER_ID,
        mention="my car",
        outcome=outcome,
        matched_entity=(
            entity or (_entity() if outcome == EntityResolutionOutcome.MATCHED else None)
        ),
        candidates=candidates,
    )


def _memory(
    number: int,
    *,
    subject: Entity | None = None,
    user_id: str = USER_ID,
    kind: MemoryKind = MemoryKind.CURRENT_STATE,
    predicate: str = "parked_at",
    value: object = "A1",
    status: MemoryStatus = MemoryStatus.ACTIVE,
    observed_at: datetime = NOW,
    occurred_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    expires_at: datetime | None = None,
    source_capture_id: UUID | None = None,
) -> Memory:
    subject_id = (subject or _entity()).id
    return Memory(
        id=_id(number),
        user_id=user_id,
        kind=kind,
        subject_entity_id=subject_id,
        predicate=predicate,
        value=value,
        status=status,
        observed_at=observed_at,
        occurred_at=occurred_at,
        valid_from=valid_from,
        valid_until=valid_until,
        expires_at=expires_at,
        memory_key=(
            Memory.build_memory_key(subject_id, predicate)
            if kind == MemoryKind.CURRENT_STATE
            else None
        ),
        source_capture_id=source_capture_id,
        created_at=observed_at,
        updated_at=observed_at,
    )


def _request(
    *,
    kind: MemoryKind | None = MemoryKind.CURRENT_STATE,
    predicate: str | None = "parked_at",
    mode: RecallMode = RecallMode.CURRENT,
    **changes: object,
) -> StructuredRecallRequest:
    data: dict[str, object] = {
        "user_id": USER_ID,
        "subject": "my car",
        "kind": kind,
        "predicate": predicate,
        "mode": mode,
    }
    data.update(changes)
    return StructuredRecallRequest.model_validate(data)


def _service(
    memories: Sequence[Memory] = (),
    *,
    resolution: EntityResolution | None = None,
    clock: FixedClock | None = None,
    honor_scope: bool = True,
) -> tuple[StructuredRecallService, StubResolver, FakeMemoryQueryRepository]:
    resolver = StubResolver(resolution or _resolution())
    repository = FakeMemoryQueryRepository(memories, honor_scope=honor_scope)
    service = StructuredRecallService(
        entity_resolver=resolver,
        memory_query_repository=repository,
        clock=clock or FixedClock(),
    )
    return service, resolver, repository


def test_matched_subject_queries_user_scope_and_preserves_provenance() -> None:
    source_id = _id(90)
    memory = _memory(10, source_capture_id=source_id)
    service, resolver, repository = _service([memory])

    result = service.recall(_request())

    assert result.outcome == RecallOutcome.FOUND
    assert result.memories == (memory,)
    assert result.memories[0].source_capture_id == source_id
    assert resolver.calls == [(USER_ID, "my car")]
    assert repository.queries[0].user_id == USER_ID
    assert repository.queries[0].statuses == (MemoryStatus.ACTIVE,)


def test_unmatched_subject_returns_not_found_without_query() -> None:
    service, _, repository = _service(
        resolution=_resolution(EntityResolutionOutcome.UNMATCHED)
    )

    result = service.recall(_request())

    assert result.outcome == RecallOutcome.NOT_FOUND
    assert repository.queries == []


def test_foreign_scope_matched_resolution_fails_closed_without_query() -> None:
    foreign = Entity(
        id=_id(91),
        user_id="foreign-user",
        type=EntityType.VEHICLE,
        canonical_name="my car",
    )
    resolution = EntityResolution(
        user_id=foreign.user_id,
        mention="my car",
        outcome=EntityResolutionOutcome.MATCHED,
        matched_entity=foreign,
    )
    service, _, repository = _service(resolution=resolution)

    with pytest.raises(RecallInvariantError, match="another user's scope"):
        service.recall(_request())

    assert repository.queries == []


def test_foreign_scope_ambiguous_resolution_fails_closed_without_leaking_ids() -> None:
    candidates = tuple(
        Entity(
            id=_id(number),
            user_id="foreign-user",
            type=EntityType.PERSON,
            canonical_name="Alex",
        )
        for number in (92, 93)
    )
    resolution = EntityResolution(
        user_id="foreign-user",
        mention="Alex",
        outcome=EntityResolutionOutcome.AMBIGUOUS,
        candidates=candidates,
    )
    service, _, repository = _service(resolution=resolution)

    with pytest.raises(RecallInvariantError, match="another user's scope"):
        service.recall(_request(subject="Alex"))

    assert repository.queries == []


def test_ambiguous_subject_is_not_disambiguated_by_expected_type() -> None:
    candidates = (
        _entity(2, name="Alex", entity_type=EntityType.PERSON),
        _entity(3, name="Alex", entity_type=EntityType.ORGANIZATION),
    )
    service, _, repository = _service(
        resolution=_resolution(EntityResolutionOutcome.AMBIGUOUS, candidates=candidates)
    )

    result = service.recall(_request(expected_subject_type=EntityType.PERSON))

    assert result.outcome == RecallOutcome.AMBIGUOUS_SUBJECT
    assert result.ambiguous_subject_ids == tuple(entity.id for entity in candidates)
    assert repository.queries == []


def test_unique_subject_type_conflict_blocks_query() -> None:
    service, _, repository = _service()

    result = service.recall(_request(expected_subject_type=EntityType.PERSON))

    assert result.outcome == RecallOutcome.SUBJECT_TYPE_CONFLICT
    assert repository.queries == []


@pytest.mark.parametrize(
    "memory",
    [
        _memory(11, valid_until=NOW - timedelta(seconds=1)),
        _memory(12, expires_at=NOW),
        _memory(13, valid_from=NOW + timedelta(seconds=1)),
    ],
)
def test_current_state_excludes_stale_expired_and_future_valid_evidence(
    memory: Memory,
) -> None:
    service, _, _ = _service([memory])

    assert service.recall(_request()).outcome == RecallOutcome.NOT_FOUND


def test_history_can_return_stale_current_state_without_mutation() -> None:
    stale = _memory(14, valid_until=NOW - timedelta(days=1))
    service, _, repository = _service([stale])

    result = service.recall(_request(mode=RecallMode.HISTORY))

    assert result.memories == (stale,)
    assert repository.queries[0].valid_at is None
    assert stale.status == MemoryStatus.ACTIVE


def test_fact_recall_returns_all_active_conflicting_values() -> None:
    kevin = _entity(4, name="Kevin", entity_type=EntityType.PERSON)
    facts = (
        _memory(20, subject=kevin, kind=MemoryKind.FACT, predicate="birthday", value="Mar 12"),
        _memory(21, subject=kevin, kind=MemoryKind.FACT, predicate="birthday", value="Mar 13"),
    )
    service, _, _ = _service(facts, resolution=_resolution(entity=kevin))

    result = service.recall(
        _request(kind=MemoryKind.FACT, predicate="birthday", mode=RecallMode.CURRENT)
    )

    assert {memory.value for memory in result.memories} == {"Mar 12", "Mar 13"}


def test_preference_recall_returns_multiple_active_preferences() -> None:
    kevin = _entity(5, name="Kevin", entity_type=EntityType.PERSON)
    preferences = tuple(
        _memory(
            30 + index,
            subject=kevin,
            kind=MemoryKind.PREFERENCE,
            predicate="likes",
            value=value,
        )
        for index, value in enumerate(("coffee", "jazz"))
    )
    service, _, _ = _service(preferences, resolution=_resolution(entity=kevin))

    result = service.recall(
        _request(kind=MemoryKind.PREFERENCE, predicate="likes", mode=RecallMode.ACTIVE)
    )

    assert {memory.value for memory in result.memories} == {"coffee", "jazz"}


def test_event_history_uses_occurred_time_with_observed_fallback_newest_first() -> None:
    observed_newer_but_occurred_older = _memory(
        40,
        kind=MemoryKind.EVENT,
        predicate="bench_press",
        observed_at=NOW,
        occurred_at=NOW - timedelta(days=3),
    )
    fallback_newest = _memory(
        41,
        kind=MemoryKind.EVENT,
        predicate="bench_press",
        observed_at=NOW - timedelta(days=1),
    )
    service, _, _ = _service([observed_newer_but_occurred_older, fallback_newest])

    result = service.recall(
        _request(kind=MemoryKind.EVENT, predicate="bench_press", mode=RecallMode.HISTORY)
    )

    assert result.memories == (fallback_newest, observed_newer_but_occurred_older)


def test_event_latest_returns_one_and_time_range_is_inclusive() -> None:
    old = _memory(
        50,
        kind=MemoryKind.EVENT,
        predicate="oil_changed",
        occurred_at=NOW - timedelta(days=10),
    )
    latest = _memory(
        51,
        kind=MemoryKind.EVENT,
        predicate="oil_changed",
        occurred_at=NOW - timedelta(days=2),
    )
    service, _, repository = _service([old, latest])

    result = service.recall(
        _request(
            kind=MemoryKind.EVENT,
            predicate="oil_changed",
            mode=RecallMode.LATEST,
            since=NOW - timedelta(days=2),
            until=NOW,
            limit=99,
        )
    )

    assert result.memories == (latest,)
    assert repository.queries[0].limit == 1


def test_active_intent_excludes_terminal_while_history_includes_it() -> None:
    active = _memory(60, kind=MemoryKind.INTENT, predicate="buy", value="milk")
    completed = _memory(
        61,
        kind=MemoryKind.INTENT,
        predicate="buy",
        value="eggs",
        status=MemoryStatus.COMPLETED,
    )
    service, _, _ = _service([completed, active])
    active_request = _request(kind=MemoryKind.INTENT, predicate="buy", mode=RecallMode.ACTIVE)
    history_request = _request(kind=MemoryKind.INTENT, predicate="buy", mode=RecallMode.HISTORY)

    assert service.recall(active_request).memories == (active,)
    assert {memory.id for memory in service.recall(history_request).memories} == {
        active.id,
        completed.id,
    }


def test_limit_is_validated_and_applied_deterministically() -> None:
    events = tuple(
        _memory(
            70 + index,
            kind=MemoryKind.EVENT,
            predicate="workout",
            occurred_at=NOW - timedelta(days=index),
        )
        for index in range(3)
    )
    service, _, _ = _service(events)

    result = service.recall(
        _request(kind=MemoryKind.EVENT, predicate="workout", mode=RecallMode.HISTORY, limit=2)
    )

    assert result.memories == events[:2]
    with pytest.raises(ValidationError):
        _request(limit=0)
    with pytest.raises(ValidationError):
        _request(limit=101)


def test_cross_user_evidence_fails_closed() -> None:
    service, _, _ = _service(
        [_memory(80, user_id="foreign-user")],
        honor_scope=False,
    )

    with pytest.raises(RecallInvariantError, match="another user's"):
        service.recall(_request())


def test_duplicate_active_current_state_slot_fails_closed() -> None:
    service, _, _ = _service([_memory(81), _memory(82)])

    with pytest.raises(RecallInvariantError, match="multiple active CURRENT_STATE"):
        service.recall(_request())


def test_latest_current_state_checks_for_duplicate_slot_before_selecting() -> None:
    service, _, repository = _service([_memory(83), _memory(84)])

    with pytest.raises(RecallInvariantError, match="multiple active CURRENT_STATE"):
        service.recall(_request(mode=RecallMode.LATEST, limit=1))

    assert repository.queries[0].limit == 2


def test_request_and_query_reject_naive_or_reversed_time_ranges() -> None:
    with pytest.raises(ValidationError):
        _request(since=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        _request(since=NOW, until=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError):
        MemoryQuery(user_id=USER_ID, observed_at_from=NOW, observed_at_until=NOW - timedelta(1))


def test_naive_clock_fails_before_memory_query() -> None:
    service, _, repository = _service(clock=FixedClock(datetime(2026, 1, 1)))

    with pytest.raises(ValueError, match="clock.now"):
        service.recall(_request())

    assert repository.queries == []
