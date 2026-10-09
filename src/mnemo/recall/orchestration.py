"""Provider-independent natural-language recall execution orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.recall.models import (
    RecallExecutionOutcome,
    RecallExecutionResult,
    RecallOutcome,
    RecallPlanOutcome,
    RecallRequestExecution,
    StructuredRecallRequest,
    StructuredRecallResult,
)
from mnemo.recall.service import StructuredRecallService

if TYPE_CHECKING:
    from mnemo.interfaces.recall import RecallPlanner


class RecallOrchestrationInvariantError(ValueError):
    """Raised when a plan or result violates the orchestration boundary."""


class RecallOrchestrationService:
    """Execute planner output exactly through deterministic structured recall."""

    def __init__(
        self,
        *,
        planner: RecallPlanner,
        structured_recall_service: StructuredRecallService,
    ) -> None:
        self._planner = planner
        self._structured_recall_service = structured_recall_service

    def recall(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallExecutionResult:
        scoped_user_id = require_non_blank(user_id, field_name="user_id")
        question_text = require_non_blank(question, field_name="question")
        reference_time = require_timezone_aware(asked_at, field_name="asked_at")

        plan = self._planner.plan(
            user_id=scoped_user_id,
            question=question_text,
            asked_at=reference_time,
        )
        if plan.outcome == RecallPlanOutcome.UNSUPPORTED:
            return RecallExecutionResult(
                outcome=RecallExecutionOutcome.UNSUPPORTED,
                planner_outcome=plan.outcome,
            )
        if plan.outcome == RecallPlanOutcome.AMBIGUOUS:
            return RecallExecutionResult(
                outcome=RecallExecutionOutcome.AMBIGUOUS_PLAN,
                planner_outcome=plan.outcome,
            )

        self._validate_request_scopes(user_id=scoped_user_id, requests=plan.requests)
        executions: list[RecallRequestExecution] = []
        for request in plan.requests:
            result = self._structured_recall_service.recall(request)
            self._validate_result_metadata(request=request, result=result)
            executions.append(RecallRequestExecution(request=request, result=result))

        return RecallExecutionResult(
            outcome=_aggregate_outcome(tuple(item.result for item in executions)),
            planner_outcome=plan.outcome,
            executions=tuple(executions),
        )

    @staticmethod
    def _validate_request_scopes(
        *,
        user_id: str,
        requests: tuple[StructuredRecallRequest, ...],
    ) -> None:
        if any(request.user_id != user_id for request in requests):
            raise RecallOrchestrationInvariantError(
                "recall plan contains a request for another user scope"
            )

    @staticmethod
    def _validate_result_metadata(
        *,
        request: StructuredRecallRequest,
        result: StructuredRecallResult,
    ) -> None:
        if (
            result.mode != request.mode
            or result.kind != request.kind
            or result.predicate != request.predicate
        ):
            raise RecallOrchestrationInvariantError(
                "structured recall result metadata does not match its request"
            )


def _aggregate_outcome(
    results: tuple[StructuredRecallResult, ...],
) -> RecallExecutionOutcome:
    outcomes = tuple(result.outcome for result in results)
    if RecallOutcome.AMBIGUOUS_SUBJECT in outcomes:
        return RecallExecutionOutcome.AMBIGUOUS_SUBJECT
    if RecallOutcome.SUBJECT_TYPE_CONFLICT in outcomes:
        return RecallExecutionOutcome.SUBJECT_TYPE_CONFLICT
    if all(outcome == RecallOutcome.FOUND for outcome in outcomes):
        return RecallExecutionOutcome.FOUND
    if all(outcome == RecallOutcome.NOT_FOUND for outcome in outcomes):
        return RecallExecutionOutcome.NOT_FOUND
    return RecallExecutionOutcome.PARTIAL
