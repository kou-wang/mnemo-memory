"""Offline tests for OpenAI Structured Outputs answer synthesis."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from openai import OpenAI, OpenAIError
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

import mnemo.providers.openai.answer_synthesizer as synthesizer_module
from mnemo import (
    AnswerSynthesizer,
    Memory,
    MemoryKind,
    MemoryStatus,
    SynthesizedAnswer,
)
from mnemo.providers.openai import (
    OpenAIAnswerProviderError,
    OpenAIAnswerResponseError,
    OpenAIAnswerSynthesizer,
)
from mnemo.providers.openai.answer_prompt import ANSWER_SYNTHESIS_INSTRUCTIONS
from mnemo.providers.openai.answer_schemas import OpenAIAnswerOutput

NOW = datetime(2026, 10, 9, 20, tzinfo=UTC)
USER_ID = "private-user-id-never-send"


def _id(number: int) -> UUID:
    return UUID(int=70_000 + number)


def _memory(number: int, *, value: object = "B7") -> Memory:
    subject_id = _id(100)
    return Memory(
        id=_id(number),
        user_id=USER_ID,
        kind=MemoryKind.CURRENT_STATE,
        subject_entity_id=subject_id,
        predicate="parked_at",
        value=value,
        status=MemoryStatus.ACTIVE,
        observed_at=NOW,
        memory_key=Memory.build_memory_key(subject_id, "parked_at"),
        source_capture_id=_id(1_000 + number),
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class _FakeResponse:
    output_parsed: object | None


class _FakeResponses:
    def __init__(self, parsed: object | None, *, error: Exception | None = None) -> None:
        self._response = _FakeResponse(parsed)
        self._error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, parsed: object | None, *, error: Exception | None = None) -> None:
        self.responses = _FakeResponses(parsed, error=error)


def _synthesize(
    parsed: OpenAIAnswerOutput,
    *,
    evidence: tuple[Memory, ...],
) -> tuple[SynthesizedAnswer, _FakeClient]:
    client = _FakeClient(parsed)
    synthesizer: AnswerSynthesizer = OpenAIAnswerSynthesizer(
        model="answer-model",
        client=cast(OpenAI, client),
    )
    answer = synthesizer.synthesize(
        question="Where did I park?",
        evidence=evidence,
        asked_at=NOW,
    )
    return answer, client


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def test_uses_configured_model_responses_parse_and_maps_uuid_citations() -> None:
    memory = _memory(1)
    answer, client = _synthesize(
        OpenAIAnswerOutput.model_validate(
            {
                "text": "You parked at B7.",
                "cited_memory_ids": [str(memory.id)],
            }
        ),
        evidence=(memory,),
    )

    call = client.responses.calls[0]
    assert call["model"] == "answer-model"
    assert call["text_format"] is OpenAIAnswerOutput
    assert answer == SynthesizedAnswer(
        text="You parked at B7.",
        cited_memory_ids=(memory.id,),
    )
    assert isinstance(answer.cited_memory_ids[0], UUID)


def test_provider_receives_only_minimal_structured_evidence_without_user_id() -> None:
    first = _memory(2)
    second = _memory(3, value="C4")
    _, client = _synthesize(
        OpenAIAnswerOutput(
            text="The supplied locations are B7 and C4.",
            cited_memory_ids=[first.id, second.id],
        ),
        evidence=(first, second),
    )

    raw_input = cast(str, client.responses.calls[0]["input"])
    payload = cast(dict[str, object], json.loads(raw_input))
    evidence = cast(list[dict[str, object]], payload["evidence"])

    assert USER_ID not in raw_input
    assert payload["asked_at"] == NOW.isoformat()
    assert payload["question"] == "Where did I park?"
    assert [item["id"] for item in evidence] == [str(first.id), str(second.id)]
    assert set(evidence[0]) == {
        "id",
        "kind",
        "predicate",
        "value",
        "status",
        "observed_at",
        "occurred_at",
        "valid_from",
        "valid_until",
        "expires_at",
        "source_capture_id",
    }
    assert "subject_entity_id" not in evidence[0]


def test_openai_answer_schema_is_strict_and_contains_no_oneof() -> None:
    schema = to_strict_json_schema(OpenAIAnswerOutput)

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["text", "cited_memory_ids"]
    assert not _contains_key(schema, "oneOf")


def test_blank_question_naive_time_and_empty_evidence_are_rejected_locally() -> None:
    memory = _memory(4)
    client = _FakeClient(None)
    synthesizer = OpenAIAnswerSynthesizer(model="model", client=cast(OpenAI, client))

    with pytest.raises(ValueError, match="question must not be blank"):
        synthesizer.synthesize(question=" ", evidence=(memory,), asked_at=NOW)
    with pytest.raises(ValueError, match="asked_at must be a timezone-aware"):
        synthesizer.synthesize(
            question="Where?",
            evidence=(memory,),
            asked_at=datetime(2026, 10, 9),
        )
    with pytest.raises(ValueError, match="evidence must contain"):
        synthesizer.synthesize(question="Where?", evidence=(), asked_at=NOW)

    assert client.responses.calls == []


def test_unparsed_malformed_and_unusable_outputs_raise_response_errors() -> None:
    memory = _memory(5)
    unparsed = OpenAIAnswerSynthesizer(
        model="model",
        client=cast(OpenAI, _FakeClient(None)),
    )
    with pytest.raises(OpenAIAnswerResponseError, match="no parsed grounded answer"):
        unparsed.synthesize(question="Where?", evidence=(memory,), asked_at=NOW)

    with pytest.raises(ValidationError) as invalid:
        OpenAIAnswerOutput.model_validate({"text": "Answer", "wrong": []})
    malformed = OpenAIAnswerSynthesizer(
        model="model",
        client=cast(OpenAI, _FakeClient(None, error=invalid.value)),
    )
    with pytest.raises(OpenAIAnswerResponseError, match="malformed structured"):
        malformed.synthesize(question="Where?", evidence=(memory,), asked_at=NOW)

    duplicate_output = OpenAIAnswerOutput(
        text="Answer",
        cited_memory_ids=[memory.id, memory.id],
    )
    unusable = OpenAIAnswerSynthesizer(
        model="model",
        client=cast(OpenAI, _FakeClient(duplicate_output)),
    )
    with pytest.raises(OpenAIAnswerResponseError, match="unusable structured"):
        unusable.synthesize(question="Where?", evidence=(memory,), asked_at=NOW)


def test_provider_error_is_sanitized() -> None:
    secret = "sk-secret-that-must-not-leak"
    client = _FakeClient(None, error=OpenAIError(secret))
    synthesizer = OpenAIAnswerSynthesizer(model="model", client=cast(OpenAI, client))

    with pytest.raises(OpenAIAnswerProviderError) as raised:
        synthesizer.synthesize(question="Where?", evidence=(_memory(6),), asked_at=NOW)

    assert secret not in str(raised.value)


def test_prompt_requires_grounding_multi_fact_preservation_and_citations() -> None:
    prompt = ANSWER_SYNTHESIS_INSTRUCTIONS.lower()

    assert "only the supplied" in prompt
    assert "never use world knowledge" in prompt
    assert "legitimate coexistence or conflicting" in prompt
    assert "cite them all" in prompt
    assert "never silently select one" in prompt
    assert "only when the question and evidence semantics" in prompt
    assert "citation ids" in prompt
    assert "retrieve additional" in prompt


def test_adapter_has_no_repository_or_recall_authority_imports() -> None:
    source = inspect.getsource(synthesizer_module)

    for forbidden in (
        "mnemo.persistence",
        "MemoryRepository",
        "EntityResolver",
        "RecallPlanner",
        "StructuredRecallService",
        "RecallOrchestrationService",
    ):
        assert forbidden not in source
