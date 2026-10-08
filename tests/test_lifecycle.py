"""Lifecycle engine tests covering all five memory kinds.

These are the deterministic behavior tests required by Sprint 1:
CURRENT_STATE append/no-op/supersede, FACT's conservative
duplicate-or-append behavior, PREFERENCE add semantics, EVENT append +
duplicate handling, INTENT complete/cancel/expire, invalid terminal
transitions, duplicate-identity tightening (object_entity_id), and
user-isolation enforcement inside reconcile().
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
    object_entity_id: UUID | None = None,
    source_capture_id: UUID | None = None,
    user_id: str = "user-1",
) -> Memory:
    entity_id = entity_id or uuid4()
    memory_key = (
        Memory.build_memory_key(entity_id, predicate) if kind == MemoryKind.CURRENT_STATE else None
    )
    return Memory(
        user_id=user_id,
        kind=kind,
        subject_entity_id=entity_id,
        predicate=predicate,
        object_entity_id=object_entity_id,
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
# FACT: conservative duplicate-or-append behavior (no auto-supersession)
# ---------------------------------------------------------------------------


def test_fact_appends_when_no_active_fact_exists() -> None:
    engine = LifecycleEngine()
    incoming = make_memory(kind=MemoryKind.FACT, value="March 12", predicate="birthday")

    decision = engine.reconcile(existing_active=[], incoming=incoming)

    assert decision.action == LifecycleAction.APPEND


def test_fact_exact_duplicate_is_noop() -> None:
    """A repeated identical capture must not blindly create duplicate history."""
    engine = LifecycleEngine()
    original = make_memory(kind=MemoryKind.FACT, value="March 12", predicate="birthday")
    repeated_capture = original.model_copy(update={"id": uuid4()})

    decision = engine.reconcile(existing_active=[original], incoming=repeated_capture)

    assert decision.action == LifecycleAction.NOOP


def test_fact_with_different_value_appends_instead_of_superseding() -> None:
    """A differing FACT value for the same subject/predicate must append,
    not auto-supersede.

    The engine cannot tell from MemoryKind.FACT alone whether a predicate
    is single-valued (e.g. birthday) or naturally multi-valued (e.g.
    has_child, owns_pet, phone_number), so an uncertain conflict must not
    silently retire history. Explicit correction semantics are a future
    design that requires an unambiguous, deterministic signal from the
    caller.
    """
    engine = LifecycleEngine()
    entity_id = uuid4()
    original = make_memory(
        kind=MemoryKind.FACT, value="March 12", predicate="birthday", entity_id=entity_id
    )
    conflicting = original.model_copy(update={"id": uuid4(), "value": "March 13"})

    decision = engine.reconcile(existing_active=[original], incoming=conflicting)

    assert decision.action == LifecycleAction.APPEND
    # History is preserved implicitly: nothing is superseded or deleted.
    assert decision.supersede_ids == []
    assert original.status == MemoryStatus.ACTIVE


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


def test_multiple_active_facts_for_the_same_subject_predicate_are_allowed() -> None:
    """Unlike CURRENT_STATE, FACT has no single-active-slot invariant:
    multi-valued predicates (e.g. owns_pet) may legitimately have several
    ACTIVE facts for the same subject + predicate.
    """
    engine = LifecycleEngine()
    entity_id = uuid4()
    first_pet = make_memory(
        kind=MemoryKind.FACT, value="dog", predicate="owns_pet", entity_id=entity_id
    )
    second_pet = make_memory(
        kind=MemoryKind.FACT, value="cat", predicate="owns_pet", entity_id=entity_id
    )
    incoming = make_memory(
        kind=MemoryKind.FACT, value="parrot", predicate="owns_pet", entity_id=entity_id
    )

    decision = engine.reconcile(existing_active=[first_pet, second_pet], incoming=incoming)

    assert decision.action == LifecycleAction.APPEND


# ---------------------------------------------------------------------------
# PREFERENCE: add semantics (Sprint 1 does not implement removal)
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


def test_different_preference_for_same_predicate_appends_not_supersedes() -> None:
    """A different value for the same subject + predicate still appends --
    PREFERENCE has no single-active-slot invariant, and Sprint 1 does not
    infer "no longer true" from a differing capture.
    """
    engine = LifecycleEngine()
    entity_id = uuid4()
    likes_whisky = make_memory(
        kind=MemoryKind.PREFERENCE, value="whisky", predicate="likes", entity_id=entity_id
    )
    likes_rum = make_memory(
        kind=MemoryKind.PREFERENCE, value="rum", predicate="likes", entity_id=entity_id
    )

    decision = engine.reconcile(existing_active=[likes_whisky], incoming=likes_rum)

    assert decision.action == LifecycleAction.APPEND
    assert decision.supersede_ids == []


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


# ---------------------------------------------------------------------------
# Duplicate identity must include object_entity_id
# ---------------------------------------------------------------------------


def test_different_object_entity_id_is_not_a_duplicate() -> None:
    """Two otherwise-identical memories with different object_entity_id
    values describe different relations and must not collapse into a
    duplicate no-op.
    """
    engine = LifecycleEngine()
    entity_id = uuid4()
    gift_for_kevin = make_memory(
        kind=MemoryKind.INTENT,
        value="racket",
        predicate="buy_for",
        entity_id=entity_id,
        object_entity_id=uuid4(),
    )
    gift_for_someone_else = gift_for_kevin.model_copy(
        update={"id": uuid4(), "object_entity_id": uuid4()}
    )

    decision = engine.reconcile(existing_active=[gift_for_kevin], incoming=gift_for_someone_else)

    assert decision.action == LifecycleAction.APPEND


def test_same_object_entity_id_is_a_duplicate() -> None:
    """Sanity check: identical object_entity_id (and everything else)
    still collapses to a no-op, confirming the new comparison only adds a
    dimension rather than breaking existing duplicate detection."""
    engine = LifecycleEngine()
    object_id = uuid4()
    original = make_memory(
        kind=MemoryKind.INTENT,
        value="racket",
        predicate="buy_for",
        object_entity_id=object_id,
    )
    repeated_capture = original.model_copy(update={"id": uuid4()})

    decision = engine.reconcile(existing_active=[original], incoming=repeated_capture)

    assert decision.action == LifecycleAction.NOOP


# ---------------------------------------------------------------------------
# User isolation: reconcile() must fail closed on cross-user input
# ---------------------------------------------------------------------------


def test_reconcile_rejects_mixed_user_current_state() -> None:
    """A foreign-user memory must never be silently filtered out."""
    engine = LifecycleEngine()
    other_users_memory = make_memory(
        kind=MemoryKind.CURRENT_STATE, value="A1", predicate="parked_at", user_id="user-2"
    )
    incoming = make_memory(
        kind=MemoryKind.CURRENT_STATE, value="B7", predicate="parked_at", user_id="user-1"
    )

    with pytest.raises(LifecycleInvariantError):
        engine.reconcile(existing_active=[other_users_memory], incoming=incoming)


def test_reconcile_rejects_mixed_user_fact() -> None:
    engine = LifecycleEngine()
    other_users_memory = make_memory(
        kind=MemoryKind.FACT, value="March 12", predicate="birthday", user_id="user-2"
    )
    incoming = make_memory(
        kind=MemoryKind.FACT, value="March 12", predicate="birthday", user_id="user-1"
    )

    with pytest.raises(LifecycleInvariantError):
        engine.reconcile(existing_active=[other_users_memory], incoming=incoming)


def test_reconcile_rejects_mixed_user_even_when_one_memory_matches() -> None:
    """Even if only one of several existing_active memories belongs to a
    different user, the whole call must fail -- not silently drop just
    that memory.
    """
    engine = LifecycleEngine()
    entity_id = uuid4()
    same_user_memory = make_memory(
        kind=MemoryKind.EVENT,
        value={"reps": 5},
        predicate="bench_press",
        entity_id=entity_id,
        user_id="user-1",
    )
    other_users_memory = make_memory(
        kind=MemoryKind.EVENT, value={"reps": 5}, predicate="bench_press", user_id="user-2"
    )
    incoming = make_memory(
        kind=MemoryKind.EVENT,
        value={"reps": 6},
        predicate="bench_press",
        entity_id=entity_id,
        user_id="user-1",
    )

    with pytest.raises(LifecycleInvariantError):
        engine.reconcile(existing_active=[same_user_memory, other_users_memory], incoming=incoming)


def test_reconcile_allows_same_user_memories() -> None:
    """Sanity check: same-user input is unaffected by the isolation check."""
    engine = LifecycleEngine()
    incoming = make_memory(
        kind=MemoryKind.FACT, value="March 12", predicate="birthday", user_id="user-1"
    )

    decision = engine.reconcile(existing_active=[], incoming=incoming)

    assert decision.action == LifecycleAction.APPEND
