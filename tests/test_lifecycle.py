"""Lifecycle engine tests covering all five memory kinds.

These are the deterministic behavior tests required by Sprint 1:
CURRENT_STATE append/no-op/supersede, FACT correction, PREFERENCE
add/remove, EVENT append + duplicate handling, INTENT complete/cancel/
expire, invalid terminal transitions, and provenance/history
preservation.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from mnemo.lifecycle.engine import (
    LifecycleAction,
    LifecycleEngine,
    LifecycleInvariantError,
)
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus


def make_memory(
    *,
    kind: MemoryKind,
    value: object,
    predicate: str = "located_at",
    entity_id: UUID | None = None,
    source_capture_id: UUID | None = None,
) -> Memory:
    entity_id = entity_id or uuid4()
    memory_key = (
        Memory.build_memory_key(entity_id, predicate) if kind == MemoryKind.CURRENT_STATE else None
    )
    return Memory(
        user_id="user-1",
        kind=kind,
        subject_entity_id=entity_id,
        predicate=predicate,
        value=value,
        memory_key=memory_key,
        source_capture_id=source_capture_id,
    )


# ---------------------------------------------------------------------------
# CURRENT_STATE: append / no-op / supersede
# ---------------------------------------------------------------------------


def test_current_state_appends_when_no_active_slot_exists() -> None:
    engine = LifecycleEngine()
    incoming = make_memory(kind=MemoryKind.CURRENT_STATE, value="A1", predicate="parked_at")

    decision = engine.reconcile(existing_active=[], incoming=incoming)

    assert decision.action == LifecycleAction.APPEND


def test_current_state_supersedes_previous_value() -> None:
    """Sequence: 'I parked at A1' -> 'I moved to B7'."""
    engine = LifecycleEngine()
    entity_id = uuid4()
    parked_at_a1 = make_memory(
        kind=MemoryKind.CURRENT_STATE, value="A1", predicate="parked_at", entity_id=entity_id
    )

    moved_to_b7 = parked_at_a1.model_copy(update={"id": uuid4(), "value": "B7"})

    decision = engine.reconcile(existing_active=[parked_at_a1], incoming=moved_to_b7)

    assert decision.action == LifecycleAction.SUPERSEDE
    assert decision.supersede_ids == [parked_at_a1.id]
    # The historical memory itself is untouched by reconcile() -- the
    # engine only decides what should happen, it never mutates inputs.
    assert parked_at_a1.status == MemoryStatus.ACTIVE
    assert parked_at_a1.value == "A1"


def test_identical_current_state_is_noop() -> None:
    engine = LifecycleEngine()
    current = make_memory(kind=MemoryKind.CURRENT_STATE, value="P3 B12", predicate="parked_at")
    incoming = current.model_copy(update={"id": uuid4()})

    decision = engine.reconcile(existing_active=[current], incoming=incoming)

    assert decision.action == LifecycleAction.NOOP


def test_current_state_rejects_multiple_active_memories_for_one_slot() -> None:
    engine = LifecycleEngine()
    entity_id = uuid4()
    first = make_memory(
        kind=MemoryKind.CURRENT_STATE, value="A1", predicate="parked_at", entity_id=entity_id
    )
    duplicate_active = first.model_copy(update={"id": uuid4(), "value": "B7"})
    incoming = make_memory(
        kind=MemoryKind.CURRENT_STATE, value="C9", predicate="parked_at", entity_id=entity_id
    )

    with pytest.raises(LifecycleInvariantError):
        engine.reconcile(existing_active=[first, duplicate_active], incoming=incoming)


# ---------------------------------------------------------------------------
# FACT: correction semantics
# ---------------------------------------------------------------------------


def test_fact_appends_when_no_active_fact_exists() -> None:
    engine = LifecycleEngine()
    incoming = make_memory(kind=MemoryKind.FACT, value="March 12", predicate="birthday")

    decision = engine.reconcile(existing_active=[], incoming=incoming)

    assert decision.action == LifecycleAction.APPEND


def test_fact_correction_supersedes_without_deleting_history() -> None:
    """Sequence: 'Kevin's birthday is March 12' -> corrected to March 13."""
    engine = LifecycleEngine()
    entity_id = uuid4()
    capture_id = uuid4()
    original = make_memory(
        kind=MemoryKind.FACT,
        value="March 12",
        predicate="birthday",
        entity_id=entity_id,
        source_capture_id=capture_id,
    )
    correction = original.model_copy(
        update={"id": uuid4(), "value": "March 13", "source_capture_id": uuid4()}
    )

    decision = engine.reconcile(existing_active=[original], incoming=correction)

    assert decision.action == LifecycleAction.SUPERSEDE
    assert decision.supersede_ids == [original.id]
    # Provenance preserved: the original fact and its source capture are
    # untouched, and the correction keeps its own distinct provenance.
    assert original.source_capture_id == capture_id
    assert correction.source_capture_id != original.source_capture_id


def test_fact_identical_value_is_noop() -> None:
    engine = LifecycleEngine()
    original = make_memory(kind=MemoryKind.FACT, value="March 12", predicate="birthday")
    repeated_capture = original.model_copy(update={"id": uuid4()})

    decision = engine.reconcile(existing_active=[original], incoming=repeated_capture)

    assert decision.action == LifecycleAction.NOOP


def test_fact_for_different_predicate_does_not_interfere() -> None:
    engine = LifecycleEngine()
    entity_id = uuid4()
    birthday = make_memory(
        kind=MemoryKind.FACT, value="March 12", predicate="birthday", entity_id=entity_id
    )
    hometown = make_memory(
        kind=MemoryKind.FACT, value="Seattle", predicate="hometown", entity_id=entity_id
    )

    decision = engine.reconcile(existing_active=[birthday], incoming=hometown)

    assert decision.action == LifecycleAction.APPEND


def test_fact_rejects_multiple_active_facts_for_one_subject_predicate() -> None:
    engine = LifecycleEngine()
    entity_id = uuid4()
    first = make_memory(
        kind=MemoryKind.FACT, value="March 12", predicate="birthday", entity_id=entity_id
    )
    duplicate_active = first.model_copy(update={"id": uuid4(), "value": "March 13"})
    incoming = make_memory(
        kind=MemoryKind.FACT, value="March 14", predicate="birthday", entity_id=entity_id
    )

    with pytest.raises(LifecycleInvariantError):
        engine.reconcile(existing_active=[first, duplicate_active], incoming=incoming)


# ---------------------------------------------------------------------------
# PREFERENCE: add / remove semantics
# ---------------------------------------------------------------------------


def test_unrelated_preferences_coexist() -> None:
    """A new preference must not replace an unrelated existing one."""
    engine = LifecycleEngine()
    entity_id = uuid4()
    likes_whisky = make_memory(
        kind=MemoryKind.PREFERENCE, value="whisky", predicate="likes", entity_id=entity_id
    )
    likes_golf = make_memory(
        kind=MemoryKind.PREFERENCE, value="golf", predicate="likes", entity_id=entity_id
    )

    decision = engine.reconcile(existing_active=[likes_whisky], incoming=likes_golf)

    assert decision.action == LifecycleAction.APPEND


def test_duplicate_preference_capture_is_noop() -> None:
    engine = LifecycleEngine()
    original = make_memory(kind=MemoryKind.PREFERENCE, value="whisky", predicate="likes")
    repeated_capture = original.model_copy(update={"id": uuid4()})

    decision = engine.reconcile(existing_active=[original], incoming=repeated_capture)

    assert decision.action == LifecycleAction.NOOP


def test_preference_removal_is_a_status_transition_not_a_reconcile_decision() -> None:
    """Removing a preference happens via status transition (e.g. DELETED),
    independent of reconcile()."""
    LifecycleEngine().validate_status_transition(
        kind=MemoryKind.PREFERENCE,
        current=MemoryStatus.ACTIVE,
        target=MemoryStatus.DELETED,
    )


# ---------------------------------------------------------------------------
# EVENT: append + duplicate handling
# ---------------------------------------------------------------------------


def test_event_memories_append_when_not_duplicates() -> None:
    engine = LifecycleEngine()
    first = make_memory(
        kind=MemoryKind.EVENT, value={"weight_lb": 185, "reps": 5}, predicate="bench_press"
    )
    second = first.model_copy(
        update={
            "id": uuid4(),
            "value": {"weight_lb": 190, "reps": 4},
        }
    )

    decision = engine.reconcile(existing_active=[first], incoming=second)

    assert decision.action == LifecycleAction.APPEND


def test_event_exact_duplicate_capture_is_noop() -> None:
    """A repeated identical capture must not blindly create duplicate history."""
    engine = LifecycleEngine()
    first = make_memory(
        kind=MemoryKind.EVENT, value={"weight_lb": 185, "reps": 5}, predicate="bench_press"
    )
    repeated_capture = first.model_copy(update={"id": uuid4()})

    decision = engine.reconcile(existing_active=[first], incoming=repeated_capture)

    assert decision.action == LifecycleAction.NOOP


def test_event_with_different_occurred_at_is_not_a_duplicate() -> None:
    engine = LifecycleEngine()
    first = make_memory(
        kind=MemoryKind.EVENT, value={"weight_lb": 185, "reps": 5}, predicate="bench_press"
    )
    first = first.model_copy(update={"occurred_at": datetime.now(UTC)})
    second = first.model_copy(
        update={"id": uuid4(), "occurred_at": first.occurred_at + timedelta(days=1)}
    )

    decision = engine.reconcile(existing_active=[first], incoming=second)

    assert decision.action == LifecycleAction.APPEND


# ---------------------------------------------------------------------------
# INTENT: complete / cancel / expire
# ---------------------------------------------------------------------------


def test_intent_appends_like_other_non_slotted_kinds() -> None:
    """Sequence: 'I want AirPods' is a fresh intent -> APPEND."""
    engine = LifecycleEngine()
    incoming = make_memory(kind=MemoryKind.INTENT, value="AirPods", predicate="buy")

    decision = engine.reconcile(existing_active=[], incoming=incoming)

    assert decision.action == LifecycleAction.APPEND


def test_intent_can_complete() -> None:
    """Sequence: 'I want AirPods' -> 'I bought them'."""
    LifecycleEngine().validate_status_transition(
        kind=MemoryKind.INTENT,
        current=MemoryStatus.ACTIVE,
        target=MemoryStatus.COMPLETED,
    )


def test_intent_can_cancel() -> None:
    LifecycleEngine().validate_status_transition(
        kind=MemoryKind.INTENT,
        current=MemoryStatus.ACTIVE,
        target=MemoryStatus.CANCELLED,
    )


def test_intent_can_expire() -> None:
    LifecycleEngine().validate_status_transition(
        kind=MemoryKind.INTENT,
        current=MemoryStatus.ACTIVE,
        target=MemoryStatus.EXPIRED,
    )


def test_completed_intent_no_longer_counts_as_active() -> None:
    """After completing the AirPods intent, active intents no longer
    include it, but the historical intent record is preserved."""
    airpods = make_memory(kind=MemoryKind.INTENT, value="AirPods", predicate="buy")
    completed = airpods.model_copy(update={"status": MemoryStatus.COMPLETED})

    active_intents = [m for m in [completed] if m.status == MemoryStatus.ACTIVE]

    assert active_intents == []
    assert completed.value == "AirPods"  # historical intent still preserved


# ---------------------------------------------------------------------------
# Invalid terminal transitions
# ---------------------------------------------------------------------------


def test_fact_cannot_complete() -> None:
    """COMPLETED/CANCELLED are INTENT-only concepts."""
    with pytest.raises(LifecycleInvariantError):
        LifecycleEngine().validate_status_transition(
            kind=MemoryKind.FACT,
            current=MemoryStatus.ACTIVE,
            target=MemoryStatus.COMPLETED,
        )


def test_event_cannot_cancel() -> None:
    with pytest.raises(LifecycleInvariantError):
        LifecycleEngine().validate_status_transition(
            kind=MemoryKind.EVENT,
            current=MemoryStatus.ACTIVE,
            target=MemoryStatus.CANCELLED,
        )


def test_terminal_status_cannot_transition_again() -> None:
    """Once SUPERSEDED, a memory cannot be revived or moved elsewhere."""
    with pytest.raises(LifecycleInvariantError):
        LifecycleEngine().validate_status_transition(
            kind=MemoryKind.FACT,
            current=MemoryStatus.SUPERSEDED,
            target=MemoryStatus.ACTIVE,
        )


def test_completed_intent_cannot_become_cancelled() -> None:
    """A second terminal transition on an already-terminal intent is rejected."""
    with pytest.raises(LifecycleInvariantError):
        LifecycleEngine().validate_status_transition(
            kind=MemoryKind.INTENT,
            current=MemoryStatus.COMPLETED,
            target=MemoryStatus.CANCELLED,
        )


def test_same_status_transition_is_always_a_noop() -> None:
    """Transitioning a status to itself is always legal, even if terminal."""
    LifecycleEngine().validate_status_transition(
        kind=MemoryKind.INTENT,
        current=MemoryStatus.DELETED,
        target=MemoryStatus.DELETED,
    )
