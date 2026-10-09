"""Deterministic grounding-invariant evaluation with a fake synthesizer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from mnemo.answers import (
    RecallAnswerInvariantError,
    RecallAnswerOutcome,
    RecallAnswerService,
    SynthesizedAnswer,
)
from mnemo.evaluation.models import AnswerGroundingEvaluationCase, EvaluationResult
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind
from mnemo.recall.models import (
    RecallExecutionOutcome,
    RecallExecutionResult,
    RecallMode,
    RecallOutcome,
    RecallPlanOutcome,
    RecallRequestExecution,
    StructuredRecallRequest,
    StructuredRecallResult,
)
from mnemo.recall.orchestration import RecallOrchestrationService

_NOW = datetime(2026, 10, 9, 20, tzinfo=UTC)
_USER_ID = "evaluation-user"


def _id(number: int) -> UUID:
    return UUID(int=100_000 + number)


def _memory(
    number: int,
    *,
    kind: MemoryKind = MemoryKind.FACT,
    predicate: str = "birthday",
    value: object = "March 12",
    user_id: str = _USER_ID,
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
        occurred_at=_NOW if kind == MemoryKind.EVENT else None,
        memory_key=(
            Memory.build_memory_key(subject_id, predicate)
            if kind == MemoryKind.CURRENT_STATE
            else None
        ),
        source_capture_id=_id(1_000 + number),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _execution(
    memories: tuple[Memory, ...],
    *,
    outcome: RecallOutcome = RecallOutcome.FOUND,
    subject: str = "Kevin",
) -> RecallRequestExecution:
    kind = memories[0].kind if memories else MemoryKind.FACT
    predicate = memories[0].predicate if memories else "birthday"
    request = StructuredRecallRequest(
        user_id=_USER_ID,
        subject=subject,
        kind=kind,
        predicate=predicate,
        mode=RecallMode.CURRENT,
    )
    return RecallRequestExecution(
        request=request,
        result=StructuredRecallResult(
            outcome=outcome,
            mode=request.mode,
            kind=request.kind,
            predicate=request.predicate,
            subject_entity_id=(memories[0].subject_entity_id if memories else None),
            memories=memories,
        ),
    )


def _recall(
    outcome: RecallExecutionOutcome,
    executions: tuple[RecallRequestExecution, ...] = (),
) -> RecallExecutionResult:
    return RecallExecutionResult(
        outcome=outcome,
        planner_outcome=(
            RecallPlanOutcome.UNSUPPORTED
            if outcome == RecallExecutionOutcome.UNSUPPORTED
            else RecallPlanOutcome.AMBIGUOUS
            if outcome == RecallExecutionOutcome.AMBIGUOUS_PLAN
            else RecallPlanOutcome.PLANNED
        ),
        executions=executions,
    )


class _RecallOrchestration:
    def __init__(self, result: RecallExecutionResult) -> None:
        self.result = result

    def recall(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallExecutionResult:
        return self.result


class _Synthesizer:
    def __init__(self, answer: SynthesizedAnswer | None) -> None:
        self.answer = answer
        self.calls: list[tuple[Memory, ...]] = []

    def synthesize(
        self,
        *,
        question: str,
        evidence: tuple[Memory, ...],
        asked_at: datetime,
    ) -> SynthesizedAnswer:
        self.calls.append(evidence)
        if self.answer is None:
            raise AssertionError("synthesizer called for an abstained case")
        return self.answer


def grounding_cases() -> tuple[AnswerGroundingEvaluationCase, ...]:
    parking = _memory(
        1, kind=MemoryKind.CURRENT_STATE, predicate="parked_at", value="B7"
    )
    birthday_one = _memory(2, value="March 12")
    birthday_two = _memory(3, value="March 13")
    phone_one = _memory(4, predicate="phone_number", value="555-1111")
    phone_two = _memory(5, predicate="phone_number", value="555-2222")
    partial_hit = _execution((parking,), subject="my car")
    partial_miss = _execution((), outcome=RecallOutcome.NOT_FOUND, subject="my passport")
    return (
        AnswerGroundingEvaluationCase(
            case_id="not_found_bypasses_synthesis",
            recall_result=_recall(RecallExecutionOutcome.NOT_FOUND),
            expected_outcome=RecallAnswerOutcome.NOT_FOUND,
            expect_synthesizer_call=False,
        ),
        AnswerGroundingEvaluationCase(
            case_id="unsupported_bypasses_synthesis",
            recall_result=_recall(RecallExecutionOutcome.UNSUPPORTED),
            expected_outcome=RecallAnswerOutcome.UNSUPPORTED,
            expect_synthesizer_call=False,
        ),
        AnswerGroundingEvaluationCase(
            case_id="ambiguous_plan_bypasses_synthesis",
            recall_result=_recall(RecallExecutionOutcome.AMBIGUOUS_PLAN),
            expected_outcome=RecallAnswerOutcome.AMBIGUOUS_PLAN,
            expect_synthesizer_call=False,
        ),
        AnswerGroundingEvaluationCase(
            case_id="ambiguous_subject_bypasses_synthesis",
            recall_result=_recall(RecallExecutionOutcome.AMBIGUOUS_SUBJECT),
            expected_outcome=RecallAnswerOutcome.AMBIGUOUS_SUBJECT,
            expect_synthesizer_call=False,
        ),
        AnswerGroundingEvaluationCase(
            case_id="subject_type_conflict_bypasses_synthesis",
            recall_result=_recall(RecallExecutionOutcome.SUBJECT_TYPE_CONFLICT),
            expected_outcome=RecallAnswerOutcome.SUBJECT_TYPE_CONFLICT,
            expect_synthesizer_call=False,
        ),
        AnswerGroundingEvaluationCase(
            case_id="found_uses_recalled_evidence",
            recall_result=_recall(
                RecallExecutionOutcome.FOUND, (_execution((parking,), subject="my car"),)
            ),
            synthesized_answer=SynthesizedAnswer(
                text="You parked at B7.", cited_memory_ids=(parking.id,)
            ),
            expected_outcome=RecallAnswerOutcome.ANSWERED,
            expect_synthesizer_call=True,
            tags=("provenance",),
        ),
        AnswerGroundingEvaluationCase(
            case_id="partial_remains_partial",
            recall_result=_recall(
                RecallExecutionOutcome.PARTIAL, (partial_hit, partial_miss)
            ),
            synthesized_answer=SynthesizedAnswer(
                text="Your car is at B7; the passport was not found.",
                cited_memory_ids=(parking.id,),
            ),
            expected_outcome=RecallAnswerOutcome.PARTIAL,
            expect_synthesizer_call=True,
        ),
        AnswerGroundingEvaluationCase(
            case_id="multiple_birthday_facts_all_cited",
            recall_result=_recall(
                RecallExecutionOutcome.FOUND,
                (_execution((birthday_one, birthday_two)),),
            ),
            synthesized_answer=SynthesizedAnswer(
                text="Saved birthday values are March 12 and March 13.",
                cited_memory_ids=(birthday_one.id, birthday_two.id),
            ),
            expected_outcome=RecallAnswerOutcome.ANSWERED,
            expect_synthesizer_call=True,
        ),
        AnswerGroundingEvaluationCase(
            case_id="multi_valued_phone_facts_valid",
            recall_result=_recall(
                RecallExecutionOutcome.FOUND,
                (_execution((phone_one, phone_two)),),
            ),
            synthesized_answer=SynthesizedAnswer(
                text="Saved numbers are 555-1111 and 555-2222.",
                cited_memory_ids=(phone_one.id, phone_two.id),
            ),
            expected_outcome=RecallAnswerOutcome.ANSWERED,
            expect_synthesizer_call=True,
        ),
        AnswerGroundingEvaluationCase(
            case_id="unknown_citation_fails_closed",
            recall_result=_recall(
                RecallExecutionOutcome.FOUND, (_execution((parking,), subject="my car"),)
            ),
            synthesized_answer=SynthesizedAnswer(
                text="Unsupported citation.", cited_memory_ids=(_id(9_999),)
            ),
            expect_synthesizer_call=True,
            expect_invariant_error=True,
        ),
        AnswerGroundingEvaluationCase(
            case_id="foreign_evidence_fails_closed",
            recall_result=_recall(
                RecallExecutionOutcome.FOUND,
                (_execution((_memory(6, user_id="foreign-user"),)),),
            ),
            synthesized_answer=SynthesizedAnswer(
                text="Must not be returned.", cited_memory_ids=(_id(6),)
            ),
            expect_synthesizer_call=False,
            expect_invariant_error=True,
        ),
    )


def evaluate_grounding() -> tuple[EvaluationResult, ...]:
    results: list[EvaluationResult] = []
    for case in grounding_cases():
        recall = _RecallOrchestration(case.recall_result)
        synthesizer = _Synthesizer(case.synthesized_answer)
        service = RecallAnswerService(
            recall_orchestration_service=cast(RecallOrchestrationService, recall),
            answer_synthesizer=synthesizer,
        )
        failures: list[str] = []
        try:
            answer = service.answer(
                user_id=_USER_ID,
                question="Evaluation question",
                asked_at=_NOW,
            )
        except RecallAnswerInvariantError as error:
            if not case.expect_invariant_error:
                failures.append(f"unexpected invariant error: {error}")
        else:
            if case.expect_invariant_error:
                failures.append("expected invariant error but answer succeeded")
            elif answer.outcome != case.expected_outcome:
                failures.append(
                    f"expected outcome {case.expected_outcome}, got {answer.outcome}"
                )
            elif answer.evidence != case.recall_result.memories:
                failures.append("answer evidence differs from deterministic recall evidence")

        was_called = bool(synthesizer.calls)
        if was_called != case.expect_synthesizer_call:
            failures.append(
                f"expected synthesizer_call={case.expect_synthesizer_call}, got {was_called}"
            )
        if was_called and synthesizer.calls[0] != case.recall_result.memories:
            failures.append("synthesizer did not receive exact ordered recall evidence")
        results.append(
            EvaluationResult(
                case_id=case.case_id,
                domain=case.domain,
                passed=not failures,
                diagnostic="; ".join(failures) if failures else None,
            )
        )
    return tuple(results)
