from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from mnemo import CandidateMemory, Capture, MemoryKind, SourceType
from mnemo.providers.openai import (
    OpenAIExtractor,
    OpenAIProviderError,
    OpenAIResponseError,
)
from mnemo.providers.openai.prompt import EXTRACTION_INSTRUCTIONS
from mnemo.providers.openai.schemas import OpenAIExtractedCandidate, OpenAIExtractionBatch


@dataclass
class _FakeResponse:
    output_parsed: object | None


class _FakeResponses:
    def __init__(
        self,
        parsed: object | None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._response = _FakeResponse(parsed)
        self._error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(
        self,
        parsed: object | None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.responses = _FakeResponses(parsed, error=error)


def _capture(text: str = "I parked at P3 B12.") -> Capture:
    captured_at = datetime(2026, 10, 8, 17, 30, tzinfo=UTC)
    return Capture(
        user_id="user-1",
        source_type=SourceType.TEXT,
        raw_text=text,
        captured_at=captured_at,
        created_at=captured_at,
    )


def _text(value: str) -> dict[str, object]:
    return {"kind": "text", "value": value}


def _integer(value: int) -> dict[str, object]:
    return {"kind": "integer", "value": value}


def _object(**fields: object) -> dict[str, object]:
    entries = []
    for name, value in fields.items():
        tagged = _integer(value) if isinstance(value, int) else _text(cast(str, value))
        entries.append({"name": name, "value": tagged})
    return {"kind": "object", "value": entries}


def _candidate(
    *,
    kind: MemoryKind,
    subject: str,
    predicate: str,
    value: dict[str, object],
    category: str | None = None,
    object_mention: str | None = None,
    occurred_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    expires_at: datetime | None = None,
) -> OpenAIExtractedCandidate:
    return OpenAIExtractedCandidate(
        kind=kind,
        category=category,
        subject=subject,
        predicate=predicate,
        object=object_mention,
        value=value,
        occurred_at=occurred_at,
        valid_from=valid_from,
        valid_until=valid_until,
        expires_at=expires_at,
    )


def _extract(
    candidates: list[OpenAIExtractedCandidate], capture: Capture | None = None
) -> tuple[tuple[CandidateMemory, ...], _FakeClient]:
    client = _FakeClient(OpenAIExtractionBatch(candidates=candidates))
    extractor = OpenAIExtractor(model="structured-model", client=cast(OpenAI, client))
    result = tuple(extractor.extract(capture or _capture()))
    return result, client


def test_maps_structured_output_exactly_to_candidate_memory() -> None:
    occurred_at = datetime(2026, 10, 7, 12, tzinfo=UTC)
    valid_until = datetime(2026, 11, 7, 12, tzinfo=UTC)
    provider_candidate = _candidate(
        kind=MemoryKind.EVENT,
        category="fitness",
        subject="me",
        predicate="bench_press",
        object_mention="barbell",
        value=_object(weight_lb=185, reps=5),
        occurred_at=occurred_at,
        valid_until=valid_until,
    )

    result, _ = _extract([provider_candidate])

    assert result == (
        CandidateMemory(
            kind=MemoryKind.EVENT,
            category="fitness",
            subject="me",
            predicate="bench_press",
            object="barbell",
            value={"weight_lb": 185, "reps": 5},
            occurred_at=occurred_at,
            valid_until=valid_until,
        ),
    )
    assert result[0].__class__.__module__ == "mnemo.models.candidate"
    assert not any(
        type(value).__module__.startswith("openai")
        for value in result[0].__dict__.values()
    )


def test_maps_nested_json_values_without_provider_objects() -> None:
    provider_candidate = _candidate(
        kind=MemoryKind.EVENT,
        subject="me",
        predicate="workout_summary",
        value={
            "kind": "list",
            "value": [
                _text("bench press"),
                {"kind": "null"},
                _object(weight_lb=185),
            ],
        },
    )

    result, _ = _extract([provider_candidate])

    assert result[0].value == ["bench press", None, {"weight_lb": 185}]


def test_valid_empty_extraction_returns_zero_candidates() -> None:
    result, _ = _extract([], _capture("Thanks!"))

    assert result == ()


@pytest.mark.parametrize(
    (
        "provider_candidate",
        "expected_kind",
        "expected_subject",
        "expected_predicate",
        "expected_value",
    ),
    [
        (
            _candidate(
                kind=MemoryKind.FACT,
                subject="Kevin",
                predicate="birthday",
                value=_text("March 12"),
            ),
            MemoryKind.FACT,
            "Kevin",
            "birthday",
            "March 12",
        ),
        (
            _candidate(
                kind=MemoryKind.PREFERENCE,
                subject="Kevin",
                predicate="likes",
                value=_text("Japanese whisky"),
            ),
            MemoryKind.PREFERENCE,
            "Kevin",
            "likes",
            "Japanese whisky",
        ),
        (
            _candidate(
                kind=MemoryKind.CURRENT_STATE,
                subject="my car",
                predicate="parked_at",
                value=_text("P3 B12"),
            ),
            MemoryKind.CURRENT_STATE,
            "my car",
            "parked_at",
            "P3 B12",
        ),
        (
            _candidate(
                kind=MemoryKind.CURRENT_STATE,
                subject="my passport",
                predicate="located_at",
                value=_text("top drawer"),
            ),
            MemoryKind.CURRENT_STATE,
            "my passport",
            "located_at",
            "top drawer",
        ),
        (
            _candidate(
                kind=MemoryKind.EVENT,
                subject="me",
                predicate="bench_press",
                value=_object(weight_lb=185, reps=5),
            ),
            MemoryKind.EVENT,
            "me",
            "bench_press",
            {"weight_lb": 185, "reps": 5},
        ),
        (
            _candidate(
                kind=MemoryKind.EVENT,
                subject="my vehicle",
                predicate="oil_changed",
                value=_object(mileage=42_800, unit="mile"),
            ),
            MemoryKind.EVENT,
            "my vehicle",
            "oil_changed",
            {"mileage": 42_800, "unit": "mile"},
        ),
        (
            _candidate(
                kind=MemoryKind.INTENT,
                category="shopping",
                subject="me",
                predicate="buy",
                value=_text("AirPods"),
            ),
            MemoryKind.INTENT,
            "me",
            "buy",
            "AirPods",
        ),
    ],
)
def test_maps_established_memory_use_cases(
    provider_candidate: OpenAIExtractedCandidate,
    expected_kind: MemoryKind,
    expected_subject: str,
    expected_predicate: str,
    expected_value: object,
) -> None:
    result, _ = _extract([provider_candidate])

    assert len(result) == 1
    assert result[0].kind == expected_kind
    assert result[0].subject == expected_subject
    assert result[0].predicate == expected_predicate
    assert result[0].value == expected_value


def test_one_capture_can_produce_multiple_preferences() -> None:
    result, _ = _extract(
        [
            _candidate(
                kind=MemoryKind.PREFERENCE,
                subject="Kevin",
                predicate="likes",
                value=_text("Japanese whisky"),
            ),
            _candidate(
                kind=MemoryKind.PREFERENCE,
                subject="Kevin",
                predicate="likes",
                value=_text("tennis"),
            ),
        ]
    )

    assert [candidate.value for candidate in result] == ["Japanese whisky", "tennis"]


def test_costco_capture_produces_three_independent_intents() -> None:
    result, _ = _extract(
        [
            _candidate(
                kind=MemoryKind.INTENT,
                category="shopping:costco",
                subject="me",
                predicate="buy",
                value=_text(item),
            )
            for item in ("eggs", "milk", "paper towels")
        ],
        _capture("Next time I go to Costco, buy eggs, milk, and paper towels."),
    )

    assert [candidate.value for candidate in result] == ["eggs", "milk", "paper towels"]
    assert all(candidate.category == "shopping:costco" for candidate in result)


def test_correction_like_fact_only_returns_new_candidate() -> None:
    result, _ = _extract(
        [
            _candidate(
                kind=MemoryKind.FACT,
                subject="Kevin",
                predicate="birthday",
                value=_text("March 13"),
            )
        ],
        _capture("Kevin's birthday is actually March 13."),
    )

    assert [(candidate.kind, candidate.value) for candidate in result] == [
        (MemoryKind.FACT, "March 13")
    ]
    assert "supersession" in EXTRACTION_INSTRUCTIONS.lower()


def test_no_parsed_output_is_distinct_from_valid_empty_extraction() -> None:
    client = _FakeClient(None)
    extractor = OpenAIExtractor(model="structured-model", client=cast(OpenAI, client))

    with pytest.raises(OpenAIResponseError, match="refused.*no parsed"):
        extractor.extract(_capture())


def test_provider_error_is_sanitized() -> None:
    secret = "sk-test-secret-that-must-not-leak"
    client = _FakeClient(None, error=OpenAIError(secret))
    extractor = OpenAIExtractor(model="structured-model", client=cast(OpenAI, client))

    with pytest.raises(OpenAIProviderError) as raised:
        extractor.extract(_capture())

    assert secret not in str(raised.value)


def test_sdk_schema_validation_error_is_reported_as_malformed_output() -> None:
    with pytest.raises(ValidationError) as invalid:
        OpenAIExtractionBatch.model_validate({"wrong": []})
    client = _FakeClient(None, error=invalid.value)
    extractor = OpenAIExtractor(model="structured-model", client=cast(OpenAI, client))

    with pytest.raises(OpenAIResponseError, match="malformed structured output"):
        extractor.extract(_capture())


def test_domain_invalid_provider_result_is_reported_as_unusable() -> None:
    provider_candidate = _candidate(
        kind=MemoryKind.CURRENT_STATE,
        subject="my car",
        predicate="parked_at",
        value=_text("P3 B12"),
        valid_from=datetime(2026, 10, 9, tzinfo=UTC),
        valid_until=datetime(2026, 10, 8, tzinfo=UTC),
    )
    client = _FakeClient(OpenAIExtractionBatch(candidates=[provider_candidate]))
    extractor = OpenAIExtractor(model="structured-model", client=cast(OpenAI, client))

    with pytest.raises(OpenAIResponseError, match="unusable extraction result"):
        extractor.extract(_capture())


def test_model_name_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="model must not be blank"):
        OpenAIExtractor(model="   ", client=cast(OpenAI, _FakeClient(None)))


def test_capture_timestamp_and_configured_model_are_sent_to_responses_parse() -> None:
    capture = _capture()
    _, client = _extract([], capture)

    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "structured-model"
    assert call["text_format"] is OpenAIExtractionBatch
    assert capture.captured_at.isoformat() in cast(str, call["input"])
    assert capture.raw_text in cast(str, call["input"])
    assert "current wall clock" not in cast(str, call["input"])


def test_provider_schema_rejects_naive_datetimes_and_unknown_fields() -> None:
    base = {
        "kind": "EVENT",
        "category": None,
        "subject": "me",
        "predicate": "bench_press",
        "object": None,
        "value": _text("set"),
        "occurred_at": "2026-10-08T12:00:00",
        "valid_from": None,
        "valid_until": None,
        "expires_at": None,
    }

    with pytest.raises(ValidationError, match="timezone-aware"):
        OpenAIExtractedCandidate.model_validate(base)

    base["occurred_at"] = "2026-10-08T12:00:00+00:00"
    base["unexpected"] = "not allowed"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OpenAIExtractedCandidate.model_validate(base)


def test_evaluation_seed_covers_established_scenarios() -> None:
    path = Path(__file__).parent / "data" / "extraction_evaluation.json"
    cases = json.loads(path.read_text(encoding="utf-8"))

    assert {case["name"] for case in cases} == {
        "birthday_fact",
        "preference",
        "parking_current_state",
        "object_location",
        "workout_event",
        "vehicle_maintenance_event",
        "shopping_intent",
        "costco_intents",
    }
    assert all(case["input"] and case["expected"] for case in cases)
    assert all(case["expected_count"] == len(case["expected"]) for case in cases)
    assert all(datetime.fromisoformat(case["reference_timestamp"]).tzinfo for case in cases)
    assert next(case for case in cases if case["name"] == "costco_intents")["expected"] == [
        {"kind": "INTENT", "subject": "me", "predicate": "buy", "value": "eggs"},
        {"kind": "INTENT", "subject": "me", "predicate": "buy", "value": "milk"},
        {
            "kind": "INTENT",
            "subject": "me",
            "predicate": "buy",
            "value": "paper towels",
        },
    ]
