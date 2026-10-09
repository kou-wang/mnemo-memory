"""Provider-independent recall orchestration behavior tests."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

import mnemo.recall.orchestration as orchestration_module
from mnemo import (
    EntityType,
    Memory,
    MemoryKind,
    MemoryStatus,
    RecallExecutionOutcome,
    RecallMode,
    RecallOrchestrationInvariantError,
    RecallOrchestrationService,
    RecallOutcome,
    RecallPlan,
    RecallPlanner,
    RecallPlanOutcome,
    StructuredRecallRequest,
    StructuredRecallResult,
)
from mnemo.recall.service import RecallInvariantError, StructuredRecallService

NOW = datetime(2026, 10, 9, 20, tzinfo=UTC)
USER_ID = "orchestration-user"


def _id(number: int) -> UUID:
    return UUID(int=30_000 + number)


class FakePlanner:
    def __init__(self, plan: RecallPlan, *, error: Exception | None = None) -> None:
        self.plan_result = plan
        self.error = error
        self.calls: list[tuple[str, str, datetime]] = []

    def plan(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallPlan:
        self.calls.append((user_id, question, asked_at))
        if self.error is not None:
            raise self.error
        return self.plan_result


class FakeStructuredRecallService:
    def __init__(
        self,
        results: Sequence[StructuredRecallResult] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self.results = tuple(results)
        self.error = error
        self.calls: list[StructuredRecallRequest] = []

    def recall(self, request: StructuredRecallRequest) -> StructuredRecallResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.results[len(self.calls) - 1]


def _request(
    number: int = 1,
    *,
    user_id: str = USER_ID,
    subject: str = "my car",
    subject_type: EntityType = EntityType.VEHICLE,
    kind: MemoryKind = MemoryKind.CURRENT_STATE,
    predicate: str = "parked_at",
    mode: RecallMode = RecallMode.CURRENT,
) -> StructuredRecallRequest:
    return StructuredRecallRequest(
        user_id=user_id,
        subject=subject,
        expected_subject_type=subject_type,
        kind=kind,
        predicate=predicate,
        mode=mode,
        limit=10 + number,
    )


def _memory(
    number: int,
    *,
    request: StructuredRecallRequest,
    value: object = "A1",
    source_capture_id: UUID | None = None,
) -> Memory:
    subject_id = _id(100 + number)
    return Memory(
        id=_id(number),
        user_id=request.user_id,
        kind=request.kind or MemoryKind.FACT,
        subject_entity_id=subject_id,
        predicate=request.predicate or "related_to",
        value=value,
        status=MemoryStatus.ACTIVE,
        observed_at=NOW,
        occurred_at=NOW if request.kind == MemoryKind.EVENT else None,
        memory_key=(
            Memory.build_memory_key(subject_id, request.predicate or "related_to")
            if request.kind == MemoryKind.CURRENT_STATE
            else None
        ),
        source_capture_id=source_capture_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _result(
    request: StructuredRecallRequest,
    outcome: RecallOutcome,
    *,
    memories: tuple[Memory, ...] = (),
) -> StructuredRecallResult:
    return StructuredRecallResult(
        outcome=outcome,
        mode=request.mode,
        kind=request.kind,
        predicate=request.predicate,
        subject_entity_id=_id(100) if outcome == RecallOutcome.FOUND else None,
        ambiguous_subject_ids=(
            (_id(201), _id(202))
            if outcome == RecallOutcome.AMBIGUOUS_SUBJECT
            else ()
        ),
        memories=memories,
    )


def _planned(*requests: StructuredRecallRequest) -> RecallPlan:
    return RecallPlan(outcome=RecallPlanOutcome.PLANNED, requests=requests)


def _service(
    plan: RecallPlan,
    results: Sequence[StructuredRecallResult] = (),
    *,
    planner_error: Exception | None = None,
    recall_error: Exception | None = None,
) -> tuple[RecallOrchestrationService, FakePlanner, FakeStructuredRecallService]:
    planner = FakePlanner(plan, error=planner_error)
    recall = FakeStructuredRecallService(results, error=recall_error)
    service = RecallOrchestrationService(
        planner=cast(RecallPlanner, planner),
        structured_recall_service=cast(StructuredRecallService, recall),
    )
    return service, planner, recall


def _execute(service: RecallOrchestrationService) -> object:
    return service.recall(
        user_id=USER_ID,
        question="Where did I park?",
        asked_at=NOW,
    )


@pytest.mark.parametrize(
    ("user_id", "question", "message"),
    [
        (" ", "Where did I park?", "user_id must not be blank"),
        (USER_ID, " \n ", "question must not be blank"),
    ],
)
def test_blank_inputs_are_rejected_before_planner_call(
    user_id: str,
    question: str,
    message: str,
) -> None:
    service, planner, recall = _service(
        RecallPlan(outcome=RecallPlanOutcome.UNSUPPORTED)
    )

    with pytest.raises(ValueError, match=message):
        service.recall(user_id=user_id, question=question, asked_at=NOW)

    assert planner.calls == []
    assert recall.calls == []


def test_naive_asked_at_is_rejected_before_planner_call() -> None:
    service, planner, recall = _service(
        RecallPlan(outcome=RecallPlanOutcome.UNSUPPORTED)
    )

    with pytest.raises(ValueError, match="asked_at must be a timezone-aware"):
        service.recall(
            user_id=USER_ID,
            question="Where did I park?",
            asked_at=datetime(2026, 10, 9),
        )

    assert planner.calls == []
    assert recall.calls == []


@pytest.mark.parametrize(
    ("planner_outcome", "execution_outcome"),
    [
        (RecallPlanOutcome.UNSUPPORTED, RecallExecutionOutcome.UNSUPPORTED),
        (RecallPlanOutcome.AMBIGUOUS, RecallExecutionOutcome.AMBIGUOUS_PLAN),
    ],
)
def test_abstained_plan_executes_zero_recall_requests(
    planner_outcome: RecallPlanOutcome,
    execution_outcome: RecallExecutionOutcome,
) -> None:
    service, planner, recall = _service(RecallPlan(outcome=planner_outcome))

    result = _execute(service)

    assert result.outcome == execution_outcome
    assert result.planner_outcome == planner_outcome
    assert result.executions == ()
    assert result.memories == ()
    assert planner.calls == [(USER_ID, "Where did I park?", NOW)]
    assert recall.calls == []


@pytest.mark.parametrize(
    ("recall_outcome", "execution_outcome"),
    [
        (RecallOutcome.NOT_FOUND, RecallExecutionOutcome.NOT_FOUND),
        (RecallOutcome.AMBIGUOUS_SUBJECT, RecallExecutionOutcome.AMBIGUOUS_SUBJECT),
        (
            RecallOutcome.SUBJECT_TYPE_CONFLICT,
            RecallExecutionOutcome.SUBJECT_TYPE_CONFLICT,
        ),
    ],
)
def test_single_non_found_result_remains_explicit(
    recall_outcome: RecallOutcome,
    execution_outcome: RecallExecutionOutcome,
) -> None:
    request = _request()
    structured_result = _result(request, recall_outcome)
    service, _, _ = _service(_planned(request), [structured_result])

    result = _execute(service)

    assert result.outcome == execution_outcome
    assert result.executions[0].result is structured_result


def test_one_found_request_returns_grounded_evidence_and_provenance() -> None:
    request = _request()
    source_id = _id(900)
    memory = _memory(1, request=request, source_capture_id=source_id)
    service, _, recall = _service(
        _planned(request),
        [_result(request, RecallOutcome.FOUND, memories=(memory,))],
    )

    result = _execute(service)

    assert result.outcome == RecallExecutionOutcome.FOUND
    assert result.memories == (memory,)
    assert result.memories[0].source_capture_id == source_id
    assert recall.calls == [request]


def test_multiple_found_requests_execute_and_flatten_in_plan_order() -> None:
    first = _request(1)
    second = _request(
        2,
        subject="Kevin",
        subject_type=EntityType.PERSON,
        kind=MemoryKind.FACT,
        predicate="birthday",
    )
    first_memory = _memory(10, request=first)
    second_memory = _memory(11, request=second, value="March 12")
    before = (first.model_dump(), second.model_dump())
    service, _, recall = _service(
        _planned(first, second),
        [
            _result(first, RecallOutcome.FOUND, memories=(first_memory,)),
            _result(second, RecallOutcome.FOUND, memories=(second_memory,)),
        ],
    )

    result = _execute(service)

    assert result.outcome == RecallExecutionOutcome.FOUND
    assert recall.calls == [first, second]
    assert tuple(execution.request for execution in result.executions) == (first, second)
    assert result.memories == (first_memory, second_memory)
    assert (first.model_dump(), second.model_dump()) == before


def test_found_and_not_found_is_partial_while_all_not_found_is_not_found() -> None:
    first = _request(1)
    second = _request(2, subject="missing")
    memory = _memory(20, request=first)
    mixed, _, _ = _service(
        _planned(first, second),
        [
            _result(first, RecallOutcome.FOUND, memories=(memory,)),
            _result(second, RecallOutcome.NOT_FOUND),
        ],
    )
    missing, _, _ = _service(
        _planned(first, second),
        [
            _result(first, RecallOutcome.NOT_FOUND),
            _result(second, RecallOutcome.NOT_FOUND),
        ],
    )

    assert _execute(mixed).outcome == RecallExecutionOutcome.PARTIAL
    assert _execute(missing).outcome == RecallExecutionOutcome.NOT_FOUND


def test_cross_user_plan_fails_before_any_recall_execution() -> None:
    own = _request(1)
    foreign = _request(2, user_id="foreign-user")
    service, _, recall = _service(_planned(own, foreign))

    with pytest.raises(RecallOrchestrationInvariantError, match="another user scope"):
        _execute(service)

    assert recall.calls == []


def test_inconsistent_result_metadata_fails_closed() -> None:
    request = _request()
    bad_result = StructuredRecallResult(
        outcome=RecallOutcome.NOT_FOUND,
        mode=request.mode,
        kind=MemoryKind.FACT,
        predicate=request.predicate,
    )
    service, _, _ = _service(_planned(request), [bad_result])

    with pytest.raises(RecallOrchestrationInvariantError, match="metadata"):
        _execute(service)


def test_conflicting_facts_and_multiple_preferences_are_preserved() -> None:
    facts = _request(
        1,
        subject="Kevin",
        subject_type=EntityType.PERSON,
        kind=MemoryKind.FACT,
        predicate="birthday",
    )
    preferences = _request(
        2,
        subject="Kevin",
        subject_type=EntityType.PERSON,
        kind=MemoryKind.PREFERENCE,
        predicate="likes",
        mode=RecallMode.ACTIVE,
    )
    fact_memories = (
        _memory(30, request=facts, value="March 12"),
        _memory(31, request=facts, value="March 13"),
    )
    preference_memories = (
        _memory(32, request=preferences, value="coffee"),
        _memory(33, request=preferences, value="jazz"),
    )
    service, _, _ = _service(
        _planned(facts, preferences),
        [
            _result(facts, RecallOutcome.FOUND, memories=fact_memories),
            _result(preferences, RecallOutcome.FOUND, memories=preference_memories),
        ],
    )

    result = _execute(service)

    assert result.memories == fact_memories + preference_memories


def test_planner_and_recall_invariant_errors_propagate() -> None:
    request = _request()
    planner_failure = RuntimeError("planner provider failed")
    recall_failure = RecallInvariantError("bad deterministic evidence")
    planner_service, _, _ = _service(
        _planned(request),
        planner_error=planner_failure,
    )
    recall_service, _, _ = _service(
        _planned(request),
        recall_error=recall_failure,
    )

    with pytest.raises(RuntimeError, match="planner provider failed"):
        _execute(planner_service)
    with pytest.raises(RecallInvariantError, match="bad deterministic evidence"):
        _execute(recall_service)


def test_result_and_orchestration_module_have_no_provider_or_persistence_leakage() -> None:
    request = _request()
    memory = _memory(40, request=request)
    service, _, _ = _service(
        _planned(request),
        [_result(request, RecallOutcome.FOUND, memories=(memory,))],
    )

    result = _execute(service)
    source = inspect.getsource(orchestration_module)

    assert not any(
        type(value).__module__.startswith(("openai", "sqlalchemy"))
        for value in (result, *result.executions, *result.memories)
    )
    for forbidden in ("mnemo.providers", "mnemo.persistence", "sqlalchemy", "openai"):
        assert forbidden not in source
