"""Canonical deterministic lifecycle contract evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from mnemo.evaluation.models import (
    EvaluationResult,
    LifecycleEvaluationCase,
)
from mnemo.lifecycle.engine import (
    LifecycleAction,
    LifecycleEngine,
    LifecycleInvariantError,
)
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus

_NOW = datetime(2026, 10, 8, 15, tzinfo=UTC)
_USER_ID = "evaluation-user"


def _id(number: int) -> UUID:
    return UUID(int=80_000 + number)


def _memory(
    number: int,
    *,
    kind: MemoryKind,
    predicate: str,
    value: object,
    user_id: str = _USER_ID,
    occurred_at: datetime | None = None,
) -> Memory:
    subject_id = _id(100)
    return Memory(
        id=_id(number),
        user_id=user_id,
        kind=kind,
        subject_entity_id=subject_id,
        predicate=predicate,
        value=value,
        observed_at=_NOW,
        occurred_at=occurred_at,
        valid_from=_NOW if kind in (MemoryKind.CURRENT_STATE, MemoryKind.INTENT) else None,
        memory_key=(
            Memory.build_memory_key(subject_id, predicate)
            if kind == MemoryKind.CURRENT_STATE
            else None
        ),
        source_capture_id=_id(1_000 + number),
        created_at=_NOW,
        updated_at=_NOW,
    )


def lifecycle_cases() -> tuple[LifecycleEvaluationCase, ...]:
    parked_a1 = _memory(
        1, kind=MemoryKind.CURRENT_STATE, predicate="parked_at", value="A1"
    )
    fact = _memory(10, kind=MemoryKind.FACT, predicate="birthday", value="March 12")
    preference = _memory(20, kind=MemoryKind.PREFERENCE, predicate="likes", value="coffee")
    event = _memory(
        30,
        kind=MemoryKind.EVENT,
        predicate="bench_press",
        value={"weight_lb": 185, "reps": 5},
        occurred_at=_NOW,
    )
    return (
        LifecycleEvaluationCase(
            case_id="current_state_append",
            incoming=parked_a1,
            expected_action=LifecycleAction.APPEND,
            tags=("current_state", "provenance"),
        ),
        LifecycleEvaluationCase(
            case_id="current_state_noop",
            existing_active=(parked_a1,),
            incoming=_memory(
                2, kind=MemoryKind.CURRENT_STATE, predicate="parked_at", value="A1"
            ),
            expected_action=LifecycleAction.NOOP,
            tags=("current_state", "deduplication"),
        ),
        LifecycleEvaluationCase(
            case_id="current_state_supersede",
            existing_active=(parked_a1,),
            incoming=_memory(
                3, kind=MemoryKind.CURRENT_STATE, predicate="parked_at", value="B7"
            ),
            expected_action=LifecycleAction.SUPERSEDE,
            expected_supersede_ids=(parked_a1.id,),
            tags=("current_state", "history"),
        ),
        LifecycleEvaluationCase(
            case_id="fact_exact_duplicate_noop",
            existing_active=(fact,),
            incoming=_memory(
                11, kind=MemoryKind.FACT, predicate="birthday", value="March 12"
            ),
            expected_action=LifecycleAction.NOOP,
            tags=("fact", "deduplication"),
        ),
        LifecycleEvaluationCase(
            case_id="fact_different_value_append",
            existing_active=(fact,),
            incoming=_memory(
                12, kind=MemoryKind.FACT, predicate="birthday", value="March 13"
            ),
            expected_action=LifecycleAction.APPEND,
            tags=("fact", "conservative"),
        ),
        LifecycleEvaluationCase(
            case_id="preference_coexistence",
            existing_active=(preference,),
            incoming=_memory(
                21, kind=MemoryKind.PREFERENCE, predicate="likes", value="jazz"
            ),
            expected_action=LifecycleAction.APPEND,
            tags=("preference",),
        ),
        LifecycleEvaluationCase(
            case_id="event_duplicate_noop",
            existing_active=(event,),
            incoming=_memory(
                31,
                kind=MemoryKind.EVENT,
                predicate="bench_press",
                value={"weight_lb": 185, "reps": 5},
                occurred_at=_NOW,
            ),
            expected_action=LifecycleAction.NOOP,
            tags=("event", "deduplication"),
        ),
        LifecycleEvaluationCase(
            case_id="intent_complete",
            incoming=_memory(40, kind=MemoryKind.INTENT, predicate="buy", value="milk"),
            expected_action=LifecycleAction.APPEND,
            transition_to=MemoryStatus.COMPLETED,
            tags=("intent", "transition"),
        ),
        LifecycleEvaluationCase(
            case_id="cross_user_fail_closed",
            existing_active=(
                _memory(
                    50,
                    kind=MemoryKind.CURRENT_STATE,
                    predicate="parked_at",
                    value="X1",
                    user_id="foreign-user",
                ),
            ),
            incoming=_memory(
                51, kind=MemoryKind.CURRENT_STATE, predicate="parked_at", value="X2"
            ),
            expect_invariant_error=True,
            tags=("security", "user_isolation"),
        ),
    )


def evaluate_lifecycle() -> tuple[EvaluationResult, ...]:
    engine = LifecycleEngine()
    results: list[EvaluationResult] = []
    for case in lifecycle_cases():
        try:
            decision = engine.reconcile(
                existing_active=list(case.existing_active),
                incoming=case.incoming,
            )
        except LifecycleInvariantError as error:
            if case.expect_invariant_error:
                results.append(
                    EvaluationResult(case_id=case.case_id, domain=case.domain, passed=True)
                )
            else:
                results.append(
                    EvaluationResult(
                        case_id=case.case_id,
                        domain=case.domain,
                        passed=False,
                        diagnostic=f"unexpected invariant error: {error}",
                    )
                )
            continue

        failures: list[str] = []
        if case.expect_invariant_error:
            failures.append("expected invariant error but reconciliation succeeded")
        if decision.action != case.expected_action:
            failures.append(
                f"expected action {case.expected_action}, got {decision.action}"
            )
        if tuple(decision.supersede_ids) != case.expected_supersede_ids:
            failures.append(
                f"expected supersede ids {case.expected_supersede_ids}, "
                f"got {tuple(decision.supersede_ids)}"
            )
        if case.transition_to is not None:
            try:
                engine.validate_status_transition(
                    kind=case.incoming.kind,
                    current=case.incoming.status,
                    target=case.transition_to,
                )
            except LifecycleInvariantError as error:
                failures.append(f"expected valid transition: {error}")
        if case.incoming.source_capture_id is None:
            failures.append("canonical incoming memory lost source provenance")
        results.append(
            EvaluationResult(
                case_id=case.case_id,
                domain=case.domain,
                passed=not failures,
                diagnostic="; ".join(failures) if failures else None,
            )
        )
    return tuple(results)
