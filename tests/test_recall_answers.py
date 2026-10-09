"""Provider-independent grounded answer orchestration tests."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

import mnemo.answers.service as answer_service_module
from mnemo import (
    NO_EVIDENCE_MESSAGE,
    Memory,
    MemoryKind,
    MemoryStatus,
    RecallAnswerInvariantError,
    RecallAnswerOutcome,
    RecallAnswerService,
    RecallExecutionOutcome,
    RecallExecutionResult,
    RecallMode,
    RecallOutcome,
    RecallPlanOutcome,
    RecallRequestExecution,
    StructuredRecallRequest,
    StructuredRecallResult,
    SynthesizedAnswer,
)
from mnemo.recall.orchestration import RecallOrchestrationService

NOW = datetime(2026, 10, 9, 20, tzinfo=UTC)
USER_ID = "answer-user"


def _id(number: int) -> UUID:
    return UUID(int=50_000 + number)


def _memory(
    number: int,
    *,
    kind: MemoryKind = MemoryKind.FACT,
    predicate: str = "birthday",
    value: object = "March 12",
    user_id: str = USER_ID,
    subject_id: UUID | None = None,
) -> Memory:
    resolved_subject_id = subject_id or _id(100)
    return Memory(
        id=_id(number),
        user_id=user_id,
        kind=kind,
        subject_entity_id=resolved_subject_id,
        predicate=predicate,
        value=value,
        status=MemoryStatus.ACTIVE,
        observed_at=NOW,
        occurred_at=NOW if kind == MemoryKind.EVENT else None,
        memory_key=(
            Memory.build_memory_key(resolved_subject_id, predicate)
            if kind == MemoryKind.CURRENT_STATE
            else None
        ),
        source_capture_id=_id(1_000 + number),
        created_at=NOW,
        updated_at=NOW,
    )


def _request(
    *,
    kind: MemoryKind = MemoryKind.FACT,
    predicate: str = "birthday",
) -> StructuredRecallRequest:
    return StructuredRecallRequest(
        user_id=USER_ID,
        subject="Kevin",
        kind=kind,
        predicate=predicate,
        mode=RecallMode.CURRENT,
    )


def _recall_result(
    outcome: RecallExecutionOutcome,
    *,
    memories: tuple[Memory, ...] = (),
) -> RecallExecutionResult:
    executions: tuple[RecallRequestExecution, ...] = ()
    if memories:
        request = _request(kind=memories[0].kind, predicate=memories[0].predicate)
        executions = (
            RecallRequestExecution(
                request=request,
                result=StructuredRecallResult(
                    outcome=RecallOutcome.FOUND,
                    mode=request.mode,
                    kind=request.kind,
                    predicate=request.predicate,
                    subject_entity_id=memories[0].subject_entity_id,
                    memories=memories,
                ),
            ),
        )
    return RecallExecutionResult(
        outcome=outcome,
        planner_outcome=RecallPlanOutcome.PLANNED,
        executions=executions,
    )


class FakeRecallOrchestration:
    def __init__(self, result: RecallExecutionResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, datetime]] = []

    def recall(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallExecutionResult:
        self.calls.append((user_id, question, asked_at))
        return self.result


class FakeAnswerSynthesizer:
    def __init__(
        self,
        answer: SynthesizedAnswer,
        *,
        error: Exception | None = None,
    ) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[str, tuple[Memory, ...], datetime]] = []

    def synthesize(
        self,
        *,
        question: str,
        evidence: tuple[Memory, ...],
        asked_at: datetime,
    ) -> SynthesizedAnswer:
        self.calls.append((question, evidence, asked_at))
        if self.error is not None:
            raise self.error
        return self.answer


def _service(
    recall_result: RecallExecutionResult,
    synthesized: SynthesizedAnswer | None = None,
    *,
    synthesis_error: Exception | None = None,
) -> tuple[RecallAnswerService, FakeRecallOrchestration, FakeAnswerSynthesizer]:
    fallback_id = recall_result.memories[0].id if recall_result.memories else _id(999)
    recall = FakeRecallOrchestration(recall_result)
    synthesizer = FakeAnswerSynthesizer(
        synthesized
        or SynthesizedAnswer(text="Grounded answer.", cited_memory_ids=(fallback_id,)),
        error=synthesis_error,
    )
    service = RecallAnswerService(
        recall_orchestration_service=cast(RecallOrchestrationService, recall),
        answer_synthesizer=synthesizer,
    )
    return service, recall, synthesizer


def _answer(service: RecallAnswerService) -> object:
    return service.answer(
        user_id=USER_ID,
        question="When is Kevin's birthday?",
        asked_at=NOW,
    )


@pytest.mark.parametrize(
    ("question", "asked_at", "message"),
    [
        (" \n ", NOW, "question must not be blank"),
        ("When is it?", datetime(2026, 10, 9), "asked_at must be a timezone-aware"),
    ],
)
def test_invalid_input_is_rejected_before_recall(
    question: str,
    asked_at: datetime,
    message: str,
) -> None:
    service, recall, synthesizer = _service(
        _recall_result(RecallExecutionOutcome.NOT_FOUND)
    )

    with pytest.raises(ValueError, match=message):
        service.answer(user_id=USER_ID, question=question, asked_at=asked_at)

    assert recall.calls == []
    assert synthesizer.calls == []


@pytest.mark.parametrize(
    ("recall_outcome", "answer_outcome", "expected_text"),
    [
        (
            RecallExecutionOutcome.NOT_FOUND,
            RecallAnswerOutcome.NOT_FOUND,
            NO_EVIDENCE_MESSAGE,
        ),
        (RecallExecutionOutcome.UNSUPPORTED, RecallAnswerOutcome.UNSUPPORTED, None),
        (
            RecallExecutionOutcome.AMBIGUOUS_PLAN,
            RecallAnswerOutcome.AMBIGUOUS_PLAN,
            None,
        ),
        (
            RecallExecutionOutcome.AMBIGUOUS_SUBJECT,
            RecallAnswerOutcome.AMBIGUOUS_SUBJECT,
            None,
        ),
        (
            RecallExecutionOutcome.SUBJECT_TYPE_CONFLICT,
            RecallAnswerOutcome.SUBJECT_TYPE_CONFLICT,
            None,
        ),
    ],
)
def test_no_evidence_and_abstention_bypass_synthesis(
    recall_outcome: RecallExecutionOutcome,
    answer_outcome: RecallAnswerOutcome,
    expected_text: str | None,
) -> None:
    service, _, synthesizer = _service(_recall_result(recall_outcome))

    result = _answer(service)

    assert result.outcome == answer_outcome
    assert result.text == expected_text
    assert result.cited_memory_ids == ()
    assert synthesizer.calls == []


def test_found_passes_exact_ordered_evidence_and_preserves_provenance() -> None:
    first = _memory(1, kind=MemoryKind.PREFERENCE, predicate="likes", value="coffee")
    second = _memory(2, kind=MemoryKind.PREFERENCE, predicate="likes", value="jazz")
    recall_result = _recall_result(
        RecallExecutionOutcome.FOUND,
        memories=(first, second),
    )
    synthesized = SynthesizedAnswer(
        text="Kevin likes coffee and jazz.",
        cited_memory_ids=(first.id, second.id),
    )
    service, _, synthesizer = _service(recall_result, synthesized)

    result = _answer(service)

    assert result.outcome == RecallAnswerOutcome.ANSWERED
    assert synthesizer.calls == [
        ("When is Kevin's birthday?", (first, second), NOW)
    ]
    assert result.evidence == (first, second)
    assert result.evidence[0].source_capture_id == first.source_capture_id
    assert result.cited_memory_ids == (first.id, second.id)


def test_partial_synthesizes_available_evidence_but_remains_partial() -> None:
    memory = _memory(3)
    recall_result = _recall_result(
        RecallExecutionOutcome.PARTIAL,
        memories=(memory,),
    )
    service, _, synthesizer = _service(recall_result)

    result = _answer(service)

    assert result.outcome == RecallAnswerOutcome.PARTIAL
    assert result.recall_result is recall_result
    assert synthesizer.calls[0][1] == (memory,)


def test_unknown_citation_fails_closed() -> None:
    memory = _memory(4)
    service, _, _ = _service(
        _recall_result(RecallExecutionOutcome.FOUND, memories=(memory,)),
        SynthesizedAnswer(text="Invented.", cited_memory_ids=(_id(9_999),)),
    )

    with pytest.raises(RecallAnswerInvariantError, match="outside the supplied evidence"):
        _answer(service)


@pytest.mark.parametrize(
    ("citations", "message"),
    [
        ((), "at least one citation"),
        ((_id(5), _id(5)), "must not contain duplicates"),
    ],
)
def test_invalid_citation_shape_fails_closed(
    citations: tuple[UUID, ...],
    message: str,
) -> None:
    memory = _memory(5)
    malformed = SynthesizedAnswer.model_construct(
        text="Malformed.",
        cited_memory_ids=citations,
    )
    service, _, _ = _service(
        _recall_result(RecallExecutionOutcome.FOUND, memories=(memory,)),
        malformed,
    )

    with pytest.raises(RecallAnswerInvariantError, match=message):
        _answer(service)


def test_synthesized_answer_model_rejects_blank_text_and_duplicate_citations() -> None:
    with pytest.raises(ValidationError, match="answer text must not be blank"):
        SynthesizedAnswer(text=" ", cited_memory_ids=(_id(1),))
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        SynthesizedAnswer(text="Answer", cited_memory_ids=(_id(1), _id(1)))


def test_multiple_birthday_facts_remain_available_and_must_all_be_cited() -> None:
    first = _memory(10, value="March 12")
    second = _memory(11, value="March 13")
    recall_result = _recall_result(
        RecallExecutionOutcome.FOUND,
        memories=(first, second),
    )
    incomplete, _, incomplete_synthesizer = _service(
        recall_result,
        SynthesizedAnswer(text="March 12.", cited_memory_ids=(first.id,)),
    )

    with pytest.raises(RecallAnswerInvariantError, match="every FACT memory"):
        _answer(incomplete)
    assert incomplete_synthesizer.calls[0][1] == (first, second)

    complete, _, _ = _service(
        recall_result,
        SynthesizedAnswer(
            text="The saved birthday values are March 12 and March 13.",
            cited_memory_ids=(first.id, second.id),
        ),
    )
    assert _answer(complete).cited_memory_ids == (first.id, second.id)


def test_legitimate_multi_valued_facts_are_preserved_and_must_all_be_cited() -> None:
    first = _memory(12, predicate="phone_number", value="555-1111")
    second = _memory(13, predicate="phone_number", value="555-2222")
    recall_result = _recall_result(
        RecallExecutionOutcome.FOUND,
        memories=(first, second),
    )
    incomplete, _, synthesizer = _service(
        recall_result,
        SynthesizedAnswer(text="Kevin's number is 555-1111.", cited_memory_ids=(first.id,)),
    )

    with pytest.raises(RecallAnswerInvariantError, match="every FACT memory"):
        _answer(incomplete)
    assert synthesizer.calls[0][1] == (first, second)

    complete, _, _ = _service(
        recall_result,
        SynthesizedAnswer(
            text="Kevin has 555-1111 and 555-2222 saved.",
            cited_memory_ids=(first.id, second.id),
        ),
    )
    result = _answer(complete)

    assert result.evidence == (first, second)
    assert result.cited_memory_ids == (first.id, second.id)


def test_foreign_evidence_fails_before_synthesis() -> None:
    foreign = _memory(20, user_id="foreign-user")
    service, _, synthesizer = _service(
        _recall_result(RecallExecutionOutcome.FOUND, memories=(foreign,))
    )

    with pytest.raises(RecallAnswerInvariantError, match="another user scope"):
        _answer(service)

    assert synthesizer.calls == []


def test_synthesizer_failure_propagates() -> None:
    memory = _memory(21)
    provider_failure = RuntimeError("provider unavailable")
    service, _, _ = _service(
        _recall_result(RecallExecutionOutcome.FOUND, memories=(memory,)),
        synthesis_error=provider_failure,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        _answer(service)


def test_answer_boundary_has_no_provider_or_persistence_leakage() -> None:
    memory = _memory(22)
    service, _, _ = _service(
        _recall_result(RecallExecutionOutcome.FOUND, memories=(memory,))
    )

    result = _answer(service)
    source = inspect.getsource(answer_service_module)

    assert not any(
        type(value).__module__.startswith(("openai", "sqlalchemy"))
        for value in (result, result.recall_result, *result.evidence)
    )
    for forbidden in ("mnemo.providers", "mnemo.persistence", "sqlalchemy", "openai"):
        assert forbidden not in source
