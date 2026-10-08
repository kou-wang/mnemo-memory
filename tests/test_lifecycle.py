from uuid import uuid4

import pytest

from mnemo.lifecycle.engine import (
    LifecycleAction,
    LifecycleEngine,
    LifecycleInvariantError,
)
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus


def make_memory(*, kind: MemoryKind, value: object, predicate: str = "located_at") -> Memory:
    entity_id = uuid4()
    return Memory(
        user_id="user-1",
        kind=kind,
        subject_entity_id=entity_id,
        predicate=predicate,
        value=value,
        memory_key=Memory.build_memory_key(entity_id, predicate),
    )


def test_current_state_supersedes_previous_value() -> None:
    engine = LifecycleEngine()
    current = make_memory(kind=MemoryKind.CURRENT_STATE, value="P3 B12")

    incoming = current.model_copy(
        update={
            "id": uuid4(),
            "value": "A2",
        }
    )

    decision = engine.reconcile(existing_active=[current], incoming=incoming)

    assert decision.action == LifecycleAction.SUPERSEDE
    assert decision.supersede_ids == [current.id]


def test_identical_current_state_is_noop() -> None:
    engine = LifecycleEngine()
    current = make_memory(kind=MemoryKind.CURRENT_STATE, value="P3 B12")
    incoming = current.model_copy(update={"id": uuid4()})

    decision = engine.reconcile(existing_active=[current], incoming=incoming)

    assert decision.action == LifecycleAction.NOOP


def test_event_memories_append_when_not_duplicates() -> None:
    engine = LifecycleEngine()
    first = make_memory(kind=MemoryKind.EVENT, value={"weight_lb": 185, "reps": 5})
    second = first.model_copy(
        update={
            "id": uuid4(),
            "value": {"weight_lb": 190, "reps": 4},
        }
    )

    decision = engine.reconcile(existing_active=[first], incoming=second)

    assert decision.action == LifecycleAction.APPEND


def test_intent_can_complete() -> None:
    LifecycleEngine().validate_status_transition(
        kind=MemoryKind.INTENT,
        current=MemoryStatus.ACTIVE,
        target=MemoryStatus.COMPLETED,
    )


def test_fact_cannot_complete() -> None:
    with pytest.raises(LifecycleInvariantError):
        LifecycleEngine().validate_status_transition(
            kind=MemoryKind.FACT,
            current=MemoryStatus.ACTIVE,
            target=MemoryStatus.COMPLETED,
        )
