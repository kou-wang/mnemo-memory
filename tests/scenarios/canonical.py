"""Canonical, deterministic consumer-memory scenarios.

These fixtures deliberately describe interpreted results rather than perform
natural-language extraction. They are reusable inputs for the current lifecycle
tests and for future storage, retrieval, temporal-query, and evaluation work.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mnemo.lifecycle.engine import LifecycleAction
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from tests.scenarios.models import Scenario, ScenarioStep, StatusTransition

USER_ID = "canonical-user"
OTHER_USER_ID = "other-user"


def _id(number: int) -> UUID:
    return UUID(int=number)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 8, hour, minute, tzinfo=UTC)


def _memory(
    *,
    memory_id: int,
    capture_id: int,
    captured_at: datetime,
    kind: MemoryKind,
    subject_id: int,
    predicate: str,
    value: Any,
    user_id: str = USER_ID,
    category: str | None = None,
    occurred_at: datetime | None = None,
) -> Memory:
    subject_entity_id = _id(subject_id)
    memory_key = (
        Memory.build_memory_key(subject_entity_id, predicate)
        if kind == MemoryKind.CURRENT_STATE
        else None
    )
    return Memory(
        id=_id(memory_id),
        user_id=user_id,
        kind=kind,
        category=category,
        subject_entity_id=subject_entity_id,
        predicate=predicate,
        value=value,
        observed_at=captured_at,
        occurred_at=occurred_at,
        valid_from=captured_at if kind in {MemoryKind.CURRENT_STATE, MemoryKind.INTENT} else None,
        memory_key=memory_key,
        source_capture_id=_id(capture_id),
        created_at=captured_at,
        updated_at=captured_at,
    )


kevin_birthday_march_12 = _memory(
    memory_id=1001,
    capture_id=2001,
    captured_at=_at(15),
    kind=MemoryKind.FACT,
    subject_id=3001,
    predicate="birthday",
    value="March 12",
)
kevin_birthday_march_13 = _memory(
    memory_id=1002,
    capture_id=2002,
    captured_at=_at(15, 5),
    kind=MemoryKind.FACT,
    subject_id=3001,
    predicate="birthday",
    value="March 13",
)
BIRTHDAY_FACT = Scenario(
    name="birthday_fact",
    steps=(
        ScenarioStep(
            source_capture_id=_id(2001),
            text="Kevin's birthday is March 12.",
            captured_at=_at(15),
            memories=(kevin_birthday_march_12,),
            expected_actions=(LifecycleAction.APPEND,),
        ),
        ScenarioStep(
            source_capture_id=_id(2002),
            text="Kevin's birthday is March 13.",
            captured_at=_at(15, 5),
            memories=(kevin_birthday_march_13,),
            expected_actions=(LifecycleAction.APPEND,),
        ),
    ),
    expected_final_statuses=(
        (kevin_birthday_march_12.id, MemoryStatus.ACTIVE),
        (kevin_birthday_march_13.id, MemoryStatus.ACTIVE),
    ),
)

kevin_likes_whisky = _memory(
    memory_id=1010,
    capture_id=2010,
    captured_at=_at(16),
    kind=MemoryKind.PREFERENCE,
    subject_id=3001,
    predicate="likes",
    value="Japanese whisky",
)
kevin_likes_tennis = _memory(
    memory_id=1011,
    capture_id=2011,
    captured_at=_at(16, 5),
    kind=MemoryKind.PREFERENCE,
    subject_id=3001,
    predicate="likes",
    value="tennis",
)
kevin_likes_whisky_repeated = _memory(
    memory_id=1012,
    capture_id=2012,
    captured_at=_at(16, 10),
    kind=MemoryKind.PREFERENCE,
    subject_id=3001,
    predicate="likes",
    value="Japanese whisky",
)
FRIEND_PREFERENCES = Scenario(
    name="friend_preferences",
    steps=(
        ScenarioStep(
            _id(2010),
            "Kevin likes Japanese whisky.",
            _at(16),
            (kevin_likes_whisky,),
            (LifecycleAction.APPEND,),
        ),
        ScenarioStep(
            _id(2011),
            "Kevin likes tennis.",
            _at(16, 5),
            (kevin_likes_tennis,),
            (LifecycleAction.APPEND,),
        ),
        ScenarioStep(
            _id(2012),
            "Kevin likes Japanese whisky.",
            _at(16, 10),
            (kevin_likes_whisky_repeated,),
            (LifecycleAction.NOOP,),
        ),
    ),
    expected_final_statuses=(
        (kevin_likes_whisky.id, MemoryStatus.ACTIVE),
        (kevin_likes_tennis.id, MemoryStatus.ACTIVE),
    ),
)

parked_p3_b12 = _memory(
    memory_id=1020,
    capture_id=2020,
    captured_at=_at(17),
    kind=MemoryKind.CURRENT_STATE,
    subject_id=3020,
    predicate="parked_at",
    value="P3 B12",
)
parked_a2 = _memory(
    memory_id=1021,
    capture_id=2021,
    captured_at=_at(17, 30),
    kind=MemoryKind.CURRENT_STATE,
    subject_id=3020,
    predicate="parked_at",
    value="A2",
)
PARKING_CURRENT_STATE = Scenario(
    name="parking_current_state",
    steps=(
        ScenarioStep(
            _id(2020),
            "I parked at P3 B12.",
            _at(17),
            (parked_p3_b12,),
            (LifecycleAction.APPEND,),
        ),
        ScenarioStep(
            _id(2021),
            "I moved my car to A2.",
            _at(17, 30),
            (parked_a2,),
            (LifecycleAction.SUPERSEDE,),
        ),
    ),
    expected_final_statuses=(
        (parked_p3_b12.id, MemoryStatus.SUPERSEDED),
        (parked_a2.id, MemoryStatus.ACTIVE),
    ),
    expected_historical_ids=(parked_p3_b12.id,),
    supported_queries=("Where is my car?", "Where was I parked earlier?"),
)

passport_top_drawer = _memory(
    memory_id=1030,
    capture_id=2030,
    captured_at=_at(18),
    kind=MemoryKind.CURRENT_STATE,
    subject_id=3030,
    predicate="located_at",
    value="top drawer",
)
passport_safe = _memory(
    memory_id=1031,
    capture_id=2031,
    captured_at=_at(18, 20),
    kind=MemoryKind.CURRENT_STATE,
    subject_id=3030,
    predicate="located_at",
    value="safe",
)
OBJECT_LOCATION = Scenario(
    name="object_location",
    steps=(
        ScenarioStep(
            _id(2030),
            "My passport is in the top drawer.",
            _at(18),
            (passport_top_drawer,),
            (LifecycleAction.APPEND,),
        ),
        ScenarioStep(
            _id(2031),
            "I moved my passport to the safe.",
            _at(18, 20),
            (passport_safe,),
            (LifecycleAction.SUPERSEDE,),
        ),
    ),
    expected_final_statuses=(
        (passport_top_drawer.id, MemoryStatus.SUPERSEDED),
        (passport_safe.id, MemoryStatus.ACTIVE),
    ),
    expected_historical_ids=(passport_top_drawer.id,),
)

workout_165 = _memory(
    memory_id=1040,
    capture_id=2040,
    captured_at=_at(19),
    kind=MemoryKind.EVENT,
    subject_id=3040,
    predicate="bench_press",
    value={"weight_lb": 165, "reps": 8},
    occurred_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
)
workout_175 = _memory(
    memory_id=1041,
    capture_id=2041,
    captured_at=_at(19, 5),
    kind=MemoryKind.EVENT,
    subject_id=3040,
    predicate="bench_press",
    value={"weight_lb": 175, "reps": 6},
    occurred_at=datetime(2026, 10, 4, 12, tzinfo=UTC),
)
workout_185 = _memory(
    memory_id=1042,
    capture_id=2042,
    captured_at=_at(19, 10),
    kind=MemoryKind.EVENT,
    subject_id=3040,
    predicate="bench_press",
    value={"weight_lb": 185, "reps": 5},
    occurred_at=datetime(2026, 10, 7, 12, tzinfo=UTC),
)
WORKOUT_HISTORY = Scenario(
    name="workout_history",
    steps=tuple(
        ScenarioStep(capture_id, text, memory.observed_at, (memory,), (LifecycleAction.APPEND,))
        for capture_id, text, memory in (
            (_id(2040), "Bench press 165 lb x 8.", workout_165),
            (_id(2041), "Bench press 175 lb x 6.", workout_175),
            (_id(2042), "Bench press 185 lb x 5.", workout_185),
        )
    ),
    expected_final_statuses=tuple(
        (memory.id, MemoryStatus.ACTIVE) for memory in (workout_165, workout_175, workout_185)
    ),
    supported_queries=("How has my bench press progressed over time?",),
)

oil_change = _memory(
    memory_id=1050,
    capture_id=2050,
    captured_at=_at(20),
    kind=MemoryKind.EVENT,
    subject_id=3050,
    predicate="oil_changed",
    value={"mileage": 42_800, "unit": "mile"},
    occurred_at=_at(20),
)
VEHICLE_MAINTENANCE = Scenario(
    name="vehicle_maintenance",
    steps=(
        ScenarioStep(
            _id(2050),
            "Changed the oil at 42,800 miles.",
            _at(20),
            (oil_change,),
            (LifecycleAction.APPEND,),
        ),
    ),
    expected_final_statuses=((oil_change.id, MemoryStatus.ACTIVE),),
    expected_historical_ids=(oil_change.id,),
)

airpods_intent = _memory(
    memory_id=1060,
    capture_id=2060,
    captured_at=_at(21),
    kind=MemoryKind.INTENT,
    subject_id=3060,
    predicate="buy",
    value="AirPods",
    category="shopping",
)
SHOPPING_INTENT = Scenario(
    name="shopping_intent",
    steps=(
        ScenarioStep(
            _id(2060),
            "I want to buy AirPods.",
            _at(21),
            (airpods_intent,),
            (LifecycleAction.APPEND,),
        ),
        ScenarioStep(
            source_capture_id=_id(2061),
            text="I bought the AirPods.",
            captured_at=_at(21, 30),
            transitions=(StatusTransition(airpods_intent.id, MemoryStatus.COMPLETED),),
        ),
    ),
    expected_final_statuses=((airpods_intent.id, MemoryStatus.COMPLETED),),
    expected_historical_ids=(airpods_intent.id,),
)

costco_items = tuple(
    _memory(
        memory_id=memory_id,
        capture_id=2070,
        captured_at=_at(22),
        kind=MemoryKind.INTENT,
        subject_id=3060,
        predicate="buy",
        value=item,
        category="shopping:costco",
    )
    for memory_id, item in ((1070, "eggs"), (1071, "milk"), (1072, "paper towels"))
)
SHOPPING_LIST_SHARED_CONTEXT = Scenario(
    name="shopping_list_shared_context",
    steps=(
        ScenarioStep(
            _id(2070),
            "Next time I go to Costco, buy eggs, milk, and paper towels.",
            _at(22),
            costco_items,
            (LifecycleAction.APPEND,) * 3,
        ),
    ),
    expected_final_statuses=tuple((memory.id, MemoryStatus.ACTIVE) for memory in costco_items),
)

workout_185_repeated = _memory(
    memory_id=1080,
    capture_id=2080,
    captured_at=_at(22, 30),
    kind=MemoryKind.EVENT,
    subject_id=3040,
    predicate="bench_press",
    value={"weight_lb": 185, "reps": 5},
    occurred_at=workout_185.occurred_at,
)
DUPLICATE_EVENT = Scenario(
    name="duplicate_event",
    initial_memories=(workout_185,),
    steps=(
        ScenarioStep(
            _id(2080),
            "Bench press 185 lb x 5.",
            _at(22, 30),
            (workout_185_repeated,),
            (LifecycleAction.NOOP,),
        ),
    ),
    expected_final_statuses=((workout_185.id, MemoryStatus.ACTIVE),),
    expected_historical_ids=(workout_185.id,),
)

other_users_parking = _memory(
    memory_id=1090,
    capture_id=2090,
    captured_at=_at(23),
    kind=MemoryKind.CURRENT_STATE,
    subject_id=3090,
    predicate="parked_at",
    value="X1",
    user_id=OTHER_USER_ID,
)
cross_user_incoming = _memory(
    memory_id=1091,
    capture_id=2091,
    captured_at=_at(23, 5),
    kind=MemoryKind.CURRENT_STATE,
    subject_id=3090,
    predicate="parked_at",
    value="X2",
)
CROSS_USER_SAFETY = Scenario(
    name="cross_user_safety",
    initial_memories=(other_users_parking,),
    steps=(
        ScenarioStep(
            _id(2091),
            "I moved my car to X2.",
            _at(23, 5),
            (cross_user_incoming,),
            (LifecycleAction.SUPERSEDE,),
        ),
    ),
    expect_invariant_error=True,
)

CANONICAL_SCENARIOS = (
    BIRTHDAY_FACT,
    FRIEND_PREFERENCES,
    PARKING_CURRENT_STATE,
    OBJECT_LOCATION,
    WORKOUT_HISTORY,
    VEHICLE_MAINTENANCE,
    SHOPPING_INTENT,
    SHOPPING_LIST_SHARED_CONTEXT,
    DUPLICATE_EVENT,
    CROSS_USER_SAFETY,
)
