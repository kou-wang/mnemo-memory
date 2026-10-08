"""Contract tests for the reusable canonical scenario dataset."""

from __future__ import annotations

from uuid import UUID

import pytest

from mnemo.lifecycle.engine import LifecycleAction, LifecycleEngine, LifecycleInvariantError
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from tests.scenarios.canonical import (
    BIRTHDAY_FACT,
    CANONICAL_SCENARIOS,
    CROSS_USER_SAFETY,
    DUPLICATE_EVENT,
    FRIEND_PREFERENCES,
    OBJECT_LOCATION,
    PARKING_CURRENT_STATE,
    SHOPPING_INTENT,
    SHOPPING_LIST_SHARED_CONTEXT,
    VEHICLE_MAINTENANCE,
    WORKOUT_HISTORY,
)
from tests.scenarios.models import Scenario


def _run_scenario(scenario: Scenario) -> dict[UUID, Memory]:
    engine = LifecycleEngine()
    stored = {memory.id: memory for memory in scenario.initial_memories}

    for step in scenario.steps:
        for incoming, expected_action in zip(
            step.memories, step.expected_actions, strict=True
        ):
            active = [memory for memory in stored.values() if memory.status == MemoryStatus.ACTIVE]
            decision = engine.reconcile(existing_active=active, incoming=incoming)
            assert decision.action == expected_action

            if decision.action == LifecycleAction.APPEND:
                stored[incoming.id] = incoming
            elif decision.action == LifecycleAction.SUPERSEDE:
                for superseded_id in decision.supersede_ids:
                    previous = stored[superseded_id]
                    stored[superseded_id] = previous.model_copy(
                        update={
                            "status": MemoryStatus.SUPERSEDED,
                            "superseded_by_id": incoming.id,
                        }
                    )
                stored[incoming.id] = incoming

        for transition in step.transitions:
            memory = stored[transition.memory_id]
            engine.validate_status_transition(
                kind=memory.kind,
                current=memory.status,
                target=transition.target,
            )
            stored[memory.id] = memory.model_copy(update={"status": transition.target})

    return stored


@pytest.mark.parametrize(
    "scenario",
    [scenario for scenario in CANONICAL_SCENARIOS if not scenario.expect_invariant_error],
    ids=lambda scenario: scenario.name,
)
def test_canonical_scenario_reaches_expected_state(scenario: Scenario) -> None:
    original_memories = {
        memory.id: memory.model_copy(deep=True)
        for memory in scenario.initial_memories
        + tuple(memory for step in scenario.steps for memory in step.memories)
    }

    stored = _run_scenario(scenario)

    assert {(memory_id, memory.status) for memory_id, memory in stored.items()} == set(
        scenario.expected_final_statuses
    )
    assert all(memory_id in stored for memory_id in scenario.expected_historical_ids)
    for memory_id, original in original_memories.items():
        fixture_memory = next(
            memory
            for memory in scenario.initial_memories
            + tuple(memory for step in scenario.steps for memory in step.memories)
            if memory.id == memory_id
        )
        assert fixture_memory == original


def test_current_state_sequences_supersede_and_preserve_provenance() -> None:
    for scenario in (PARKING_CURRENT_STATE, OBJECT_LOCATION):
        stored = _run_scenario(scenario)
        old_memory = scenario.steps[0].memories[0]
        new_memory = scenario.steps[1].memories[0]

        assert scenario.steps[1].expected_actions == (LifecycleAction.SUPERSEDE,)
        assert stored[old_memory.id].status == MemoryStatus.SUPERSEDED
        assert stored[old_memory.id].superseded_by_id == new_memory.id
        assert stored[old_memory.id].source_capture_id == scenario.steps[0].source_capture_id
        assert stored[new_memory.id].status == MemoryStatus.ACTIVE
        assert old_memory.subject_entity_id == new_memory.subject_entity_id


def test_preferences_coexist_and_exact_repeat_is_noop() -> None:
    stored = _run_scenario(FRIEND_PREFERENCES)

    assert FRIEND_PREFERENCES.steps[-1].expected_actions == (LifecycleAction.NOOP,)
    assert {memory.value for memory in stored.values()} == {"Japanese whisky", "tennis"}


def test_differing_birthday_facts_append_conservatively() -> None:
    stored = _run_scenario(BIRTHDAY_FACT)

    assert {memory.value for memory in stored.values()} == {"March 12", "March 13"}
    assert all(memory.status == MemoryStatus.ACTIVE for memory in stored.values())


def test_workouts_are_distinct_append_only_events() -> None:
    stored = _run_scenario(WORKOUT_HISTORY)
    occurred_at = {memory.occurred_at for memory in stored.values()}

    assert len(stored) == 3
    assert len(occurred_at) == 3
    assert all(memory.kind == MemoryKind.EVENT for memory in stored.values())


def test_vehicle_maintenance_has_structured_mileage() -> None:
    memory = VEHICLE_MAINTENANCE.steps[0].memories[0]

    assert memory.value == {"mileage": 42_800, "unit": "mile"}
    assert memory.occurred_at is not None


def test_completed_shopping_intent_is_historical_not_active() -> None:
    stored = _run_scenario(SHOPPING_INTENT)
    completed = stored[next(iter(stored))]

    assert completed.status == MemoryStatus.COMPLETED
    assert completed.id in SHOPPING_INTENT.expected_historical_ids
    assert completed.id not in SHOPPING_INTENT.expected_active_ids
    assert completed.source_capture_id == SHOPPING_INTENT.steps[0].source_capture_id


def test_one_costco_capture_yields_three_context_sharing_intents() -> None:
    stored = _run_scenario(SHOPPING_LIST_SHARED_CONTEXT)

    assert {memory.value for memory in stored.values()} == {"eggs", "milk", "paper towels"}
    assert {memory.category for memory in stored.values()} == {"shopping:costco"}
    assert len({memory.source_capture_id for memory in stored.values()}) == 1
    assert all(memory.kind == MemoryKind.INTENT for memory in stored.values())


def test_duplicate_event_is_noop_without_a_second_history_entry() -> None:
    stored = _run_scenario(DUPLICATE_EVENT)

    assert DUPLICATE_EVENT.steps[0].expected_actions == (LifecycleAction.NOOP,)
    assert len(stored) == 1
    stored_source = next(iter(stored.values())).source_capture_id
    assert stored_source == DUPLICATE_EVENT.initial_memories[0].source_capture_id


def test_cross_user_scenario_fails_closed() -> None:
    with pytest.raises(LifecycleInvariantError):
        _run_scenario(CROSS_USER_SAFETY)


def test_all_fixture_datetimes_are_fixed_timezone_aware_values() -> None:
    for scenario in CANONICAL_SCENARIOS:
        for step in scenario.steps:
            assert step.captured_at.tzinfo is not None
            assert step.captured_at.utcoffset() is not None
            for memory in step.memories:
                assert memory.observed_at == step.captured_at
                assert memory.created_at == step.captured_at
                assert memory.updated_at == step.captured_at
