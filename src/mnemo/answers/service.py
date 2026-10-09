"""Provider-independent orchestration from grounded recall to an answer."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from mnemo.answers.models import (
    NO_EVIDENCE_MESSAGE,
    RecallAnswerOutcome,
    RecallAnswerResult,
    SynthesizedAnswer,
)
from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind
from mnemo.recall.models import RecallExecutionOutcome, RecallExecutionResult
from mnemo.recall.orchestration import RecallOrchestrationService

if TYPE_CHECKING:
    from mnemo.interfaces.answers import AnswerSynthesizer


class RecallAnswerInvariantError(ValueError):
    """Raised when grounded synthesis violates the answer boundary."""


class RecallAnswerService:
    """Phrase deterministic recall evidence without adding retrieval authority."""

    def __init__(
        self,
        *,
        recall_orchestration_service: RecallOrchestrationService,
        answer_synthesizer: AnswerSynthesizer,
    ) -> None:
        self._recall_orchestration_service = recall_orchestration_service
        self._answer_synthesizer = answer_synthesizer

    def answer(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallAnswerResult:
        scoped_user_id = require_non_blank(user_id, field_name="user_id")
        question_text = require_non_blank(question, field_name="question")
        reference_time = require_timezone_aware(asked_at, field_name="asked_at")
        recall_result = self._recall_orchestration_service.recall(
            user_id=scoped_user_id,
            question=question_text,
            asked_at=reference_time,
        )

        deterministic_outcome = _non_synthesis_outcome(recall_result.outcome)
        if deterministic_outcome is not None:
            return RecallAnswerResult(
                outcome=deterministic_outcome,
                text=(
                    NO_EVIDENCE_MESSAGE
                    if deterministic_outcome == RecallAnswerOutcome.NOT_FOUND
                    else None
                ),
                recall_result=recall_result,
            )

        evidence = recall_result.memories
        self._validate_evidence(user_id=scoped_user_id, evidence=evidence)
        synthesized = self._answer_synthesizer.synthesize(
            question=question_text,
            evidence=evidence,
            asked_at=reference_time,
        )
        self._validate_synthesis(
            synthesized=synthesized,
            evidence=evidence,
            recall_result=recall_result,
        )

        return RecallAnswerResult(
            outcome=(
                RecallAnswerOutcome.ANSWERED
                if recall_result.outcome == RecallExecutionOutcome.FOUND
                else RecallAnswerOutcome.PARTIAL
            ),
            text=synthesized.text,
            cited_memory_ids=synthesized.cited_memory_ids,
            recall_result=recall_result,
        )

    @staticmethod
    def _validate_evidence(*, user_id: str, evidence: tuple[Memory, ...]) -> None:
        if not evidence:
            raise RecallAnswerInvariantError(
                "FOUND and PARTIAL recall outcomes require grounded evidence"
            )
        if any(memory.user_id != user_id for memory in evidence):
            raise RecallAnswerInvariantError(
                "recall evidence contains a memory from another user scope"
            )

    @staticmethod
    def _validate_synthesis(
        *,
        synthesized: SynthesizedAnswer,
        evidence: tuple[Memory, ...],
        recall_result: RecallExecutionResult,
    ) -> None:
        cited_ids = synthesized.cited_memory_ids
        if not cited_ids:
            raise RecallAnswerInvariantError("a grounded answer requires at least one citation")
        if len(cited_ids) != len(set(cited_ids)):
            raise RecallAnswerInvariantError(
                "grounded answer citations must not contain duplicates"
            )

        evidence_ids = {memory.id for memory in evidence}
        unknown_ids = set(cited_ids) - evidence_ids
        if unknown_ids:
            raise RecallAnswerInvariantError(
                "grounded answer cites memory ids outside the supplied evidence"
            )

        required_fact_ids = _multi_fact_request_ids(recall_result)
        if not required_fact_ids.issubset(cited_ids):
            raise RecallAnswerInvariantError(
                "grounded answer must cite every FACT memory returned by a "
                "multi-memory FACT request"
            )


def _non_synthesis_outcome(
    outcome: RecallExecutionOutcome,
) -> RecallAnswerOutcome | None:
    return {
        RecallExecutionOutcome.NOT_FOUND: RecallAnswerOutcome.NOT_FOUND,
        RecallExecutionOutcome.UNSUPPORTED: RecallAnswerOutcome.UNSUPPORTED,
        RecallExecutionOutcome.AMBIGUOUS_PLAN: RecallAnswerOutcome.AMBIGUOUS_PLAN,
        RecallExecutionOutcome.AMBIGUOUS_SUBJECT: RecallAnswerOutcome.AMBIGUOUS_SUBJECT,
        RecallExecutionOutcome.SUBJECT_TYPE_CONFLICT: (
            RecallAnswerOutcome.SUBJECT_TYPE_CONFLICT
        ),
    }.get(outcome)


def _multi_fact_request_ids(recall_result: RecallExecutionResult) -> set[UUID]:
    required_ids: set[UUID] = set()
    for execution in recall_result.executions:
        if execution.request.kind != MemoryKind.FACT:
            continue
        fact_memories = tuple(
            memory
            for memory in execution.result.memories
            if memory.kind == MemoryKind.FACT
        )
        if len(fact_memories) > 1:
            required_ids.update(memory.id for memory in fact_memories)
    return required_ids
