"""Offline tests for OpenAI Structured Outputs recall planning."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from openai import OpenAI, OpenAIError
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

import mnemo.providers.openai.recall_planner as planner_module
from mnemo import (
    EntityType,
    MemoryKind,
    RecallMode,
    RecallPlan,
    RecallPlanner,
    RecallPlanOutcome,
    StructuredRecallRequest,
)
from mnemo.providers.openai import (
    OpenAIRecallPlanner,
    OpenAIRecallProviderError,
    OpenAIRecallResponseError,
)
from mnemo.providers.openai.recall_prompt import RECALL_PLANNING_INSTRUCTIONS
from mnemo.providers.openai.recall_schemas import (
    OpenAIPlannedRecallRequest,
    OpenAIRecallPlanOutput,
)

ASKED_AT = datetime(2026, 10, 9, 15, 30, tzinfo=UTC)
USER_ID = "planner-user"


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


def _provider_request(
    *,
    subject: str,
    subject_type: EntityType,
    kind: MemoryKind,
    predicate: str | None,
    mode: RecallMode,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 20,
) -> OpenAIPlannedRecallRequest:
    return OpenAIPlannedRecallRequest(
        subject=subject,
        expected_subject_type=subject_type,
        kind=kind,
        predicate=predicate,
        mode=mode,
        since=since,
        until=until,
        limit=limit,
    )


def _run_plan(
    question: str,
    *,
    outcome: RecallPlanOutcome = RecallPlanOutcome.PLANNED,
    requests: list[OpenAIPlannedRecallRequest] | None = None,
    asked_at: datetime = ASKED_AT,
) -> tuple[RecallPlan, _FakeClient]:
    parsed = OpenAIRecallPlanOutput(outcome=outcome, requests=requests or [])
    client = _FakeClient(parsed)
    planner: RecallPlanner = OpenAIRecallPlanner(
        model="recall-planning-model",
        client=cast(OpenAI, client),
    )
    return planner.plan(user_id=USER_ID, question=question, asked_at=asked_at), client


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


@pytest.mark.parametrize(
    (
        "question",
        "subject",
        "subject_type",
        "kind",
        "predicate",
        "mode",
    ),
    [
        (
            "Where did I park?",
            "my car",
            EntityType.VEHICLE,
            MemoryKind.CURRENT_STATE,
            "parked_at",
            RecallMode.CURRENT,
        ),
        (
            "Where is my passport?",
            "my passport",
            EntityType.OBJECT,
            MemoryKind.CURRENT_STATE,
            "located_at",
            RecallMode.CURRENT,
        ),
        (
            "When is Kevin's birthday?",
            "Kevin",
            EntityType.PERSON,
            MemoryKind.FACT,
            "birthday",
            RecallMode.CURRENT,
        ),
        (
            "What does Kevin like?",
            "Kevin",
            EntityType.PERSON,
            MemoryKind.PREFERENCE,
            "likes",
            RecallMode.ACTIVE,
        ),
        (
            "Show my recent bench press history.",
            "me",
            EntityType.PERSON,
            MemoryKind.EVENT,
            "bench_press",
            RecallMode.HISTORY,
        ),
        (
            "When did I last change the oil?",
            "my vehicle",
            EntityType.VEHICLE,
            MemoryKind.EVENT,
            "oil_changed",
            RecallMode.LATEST,
        ),
        (
            "What am I still planning to buy?",
            "me",
            EntityType.PERSON,
            MemoryKind.INTENT,
            "buy",
            RecallMode.ACTIVE,
        ),
    ],
)
def test_canonical_questions_map_to_structured_recall_requests(
    question: str,
    subject: str,
    subject_type: EntityType,
    kind: MemoryKind,
    predicate: str,
    mode: RecallMode,
) -> None:
    provider_request = _provider_request(
        subject=subject,
        subject_type=subject_type,
        kind=kind,
        predicate=predicate,
        mode=mode,
    )

    plan, _ = _run_plan(question, requests=[provider_request])

    assert plan == RecallPlan(
        outcome=RecallPlanOutcome.PLANNED,
        requests=(
            StructuredRecallRequest(
                user_id=USER_ID,
                subject=subject,
                expected_subject_type=subject_type,
                kind=kind,
                predicate=predicate,
                mode=mode,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("question", "subject", "subject_type", "predicate", "since", "until"),
    [
        (
            "What workouts did I log this week?",
            "me",
            EntityType.PERSON,
            None,
            datetime(2026, 10, 5, tzinfo=UTC),
            ASKED_AT,
        ),
        (
            "What did I bench yesterday?",
            "me",
            EntityType.PERSON,
            "bench_press",
            datetime(2026, 10, 8, tzinfo=UTC),
            datetime(2026, 10, 8, 23, 59, 59, 999999, tzinfo=UTC),
        ),
        (
            "What maintenance did I record last month?",
            "my vehicle",
            EntityType.VEHICLE,
            None,
            datetime(2026, 9, 1, tzinfo=UTC),
            datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=UTC),
        ),
    ],
)
def test_relative_time_is_mapped_from_supplied_asked_at(
    question: str,
    subject: str,
    subject_type: EntityType,
    predicate: str | None,
    since: datetime,
    until: datetime,
) -> None:
    provider_request = _provider_request(
        subject=subject,
        subject_type=subject_type,
        kind=MemoryKind.EVENT,
        predicate=predicate,
        mode=RecallMode.HISTORY,
        since=since,
        until=until,
    )

    plan, client = _run_plan(question, requests=[provider_request])

    request = plan.requests[0]
    assert request.since == since
    assert request.until == until
    assert request.since is not None and request.since.tzinfo is not None
    assert request.until is not None and request.until.tzinfo is not None
    sent_input = cast(str, client.responses.calls[0]["input"])
    assert ASKED_AT.isoformat() in sent_input
    assert question in sent_input


def test_blank_question_and_naive_asked_at_are_rejected_before_provider_call() -> None:
    client = _FakeClient(None)
    planner = OpenAIRecallPlanner(model="model", client=cast(OpenAI, client))

    with pytest.raises(ValueError, match="question must not be blank"):
        planner.plan(user_id=USER_ID, question=" \n ", asked_at=ASKED_AT)
    with pytest.raises(ValueError, match="asked_at must be a timezone-aware"):
        planner.plan(
            user_id=USER_ID,
            question="Where did I park?",
            asked_at=datetime(2026, 10, 9),
        )

    assert client.responses.calls == []


@pytest.mark.parametrize(
    "outcome",
    [RecallPlanOutcome.UNSUPPORTED, RecallPlanOutcome.AMBIGUOUS],
)
def test_valid_abstention_is_explicit_and_has_no_requests(
    outcome: RecallPlanOutcome,
) -> None:
    plan, _ = _run_plan("Handle this safely", outcome=outcome)

    assert plan.outcome == outcome
    assert plan.requests == ()


def test_valid_unsupported_plan_is_distinct_from_provider_failure() -> None:
    plan, _ = _run_plan("Find similar notes", outcome=RecallPlanOutcome.UNSUPPORTED)
    secret = "sk-secret-that-must-not-leak"
    client = _FakeClient(None, error=OpenAIError(secret))
    planner = OpenAIRecallPlanner(model="model", client=cast(OpenAI, client))

    assert plan == RecallPlan(outcome=RecallPlanOutcome.UNSUPPORTED)
    with pytest.raises(OpenAIRecallProviderError) as raised:
        planner.plan(user_id=USER_ID, question="Where did I park?", asked_at=ASKED_AT)
    assert secret not in str(raised.value)


def test_unparsed_and_malformed_provider_outputs_raise_response_errors() -> None:
    unparsed = OpenAIRecallPlanner(model="model", client=cast(OpenAI, _FakeClient(None)))
    with pytest.raises(OpenAIRecallResponseError, match="no parsed recall plan"):
        unparsed.plan(user_id=USER_ID, question="Where did I park?", asked_at=ASKED_AT)

    with pytest.raises(ValidationError) as invalid:
        OpenAIRecallPlanOutput.model_validate({"outcome": "PLANNED", "wrong": []})
    malformed = OpenAIRecallPlanner(
        model="model",
        client=cast(OpenAI, _FakeClient(None, error=invalid.value)),
    )
    with pytest.raises(OpenAIRecallResponseError, match="malformed structured"):
        malformed.plan(user_id=USER_ID, question="Where did I park?", asked_at=ASKED_AT)


def test_configured_model_and_strict_format_are_sent_to_responses_parse() -> None:
    request = _provider_request(
        subject="my car",
        subject_type=EntityType.VEHICLE,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        mode=RecallMode.CURRENT,
    )
    plan, client = _run_plan("Where did I park?", requests=[request])

    call = client.responses.calls[0]
    assert call["model"] == "recall-planning-model"
    assert call["text_format"] is OpenAIRecallPlanOutput
    assert plan.__class__.__module__ == "mnemo.recall.models"
    assert plan.requests[0].__class__.__module__ == "mnemo.recall.models"
    assert not any(
        type(value).__module__.startswith("openai")
        for value in plan.requests[0].__dict__.values()
    )


def test_openai_recall_schema_is_strict_and_contains_no_oneof() -> None:
    schema = to_strict_json_schema(OpenAIRecallPlanOutput)

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["outcome", "requests"]
    assert not _contains_key(schema, "oneOf")
    assert _contains_key(schema, "anyOf")

    definitions = cast(dict[str, object], schema["$defs"])
    request_schema = cast(dict[str, object], definitions["OpenAIPlannedRecallRequest"])
    assert request_schema["type"] == "object"
    assert request_schema["additionalProperties"] is False
    assert set(cast(list[str], request_schema["required"])) == {
        "subject",
        "expected_subject_type",
        "kind",
        "predicate",
        "mode",
        "since",
        "until",
        "limit",
    }


def test_provider_schema_rejects_bad_outcome_shapes_and_unknown_fields() -> None:
    request = _provider_request(
        subject="my car",
        subject_type=EntityType.VEHICLE,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        mode=RecallMode.CURRENT,
    )
    with pytest.raises(ValidationError, match="PLANNED requires"):
        OpenAIRecallPlanOutput(outcome=RecallPlanOutcome.PLANNED, requests=[])
    with pytest.raises(ValidationError, match="cannot contain requests"):
        OpenAIRecallPlanOutput(outcome=RecallPlanOutcome.AMBIGUOUS, requests=[request])
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OpenAIRecallPlanOutput.model_validate(
            {"outcome": "UNSUPPORTED", "requests": [], "unexpected": True}
        )


def test_model_and_user_id_validation_are_local_and_user_id_is_not_sent() -> None:
    client = _FakeClient(OpenAIRecallPlanOutput(outcome="UNSUPPORTED", requests=[]))
    with pytest.raises(ValueError, match="model must not be blank"):
        OpenAIRecallPlanner(model="   ", client=cast(OpenAI, client))

    planner = OpenAIRecallPlanner(model="model", client=cast(OpenAI, client))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        planner.plan(user_id=" ", question="Where did I park?", asked_at=ASKED_AT)
    plan = planner.plan(user_id="  scoped-user  ", question="Find similar notes", asked_at=ASKED_AT)

    assert plan.outcome == RecallPlanOutcome.UNSUPPORTED
    assert "scoped-user" not in cast(str, client.responses.calls[0]["input"])


def test_planner_has_no_deterministic_system_authority_imports() -> None:
    source = inspect.getsource(planner_module)

    for forbidden in (
        "mnemo.persistence",
        "mnemo.entities",
        "mnemo.lifecycle",
        "MemoryRepository",
        "EntityResolver",
        "StructuredRecallService",
    ):
        assert forbidden not in source


def test_prompt_documents_abstention_authority_and_canonical_time_rules() -> None:
    prompt = RECALL_PLANNING_INSTRUCTIONS.lower()

    assert "unsupported" in prompt
    assert "ambiguous" in prompt
    assert "never use a wall clock" in prompt
    assert "monday" in prompt
    assert "synthesize" in prompt


def test_recall_planning_evaluation_seed_covers_canonical_questions() -> None:
    path = Path(__file__).parent / "data" / "recall_planning_evaluation.json"
    cases = json.loads(path.read_text(encoding="utf-8"))

    assert {case["name"] for case in cases} == {
        "parking_current",
        "passport_current",
        "birthday_fact",
        "friend_preferences",
        "bench_history",
        "latest_oil_change",
        "active_shopping",
        "workouts_this_week",
        "bench_yesterday",
        "maintenance_last_month",
        "unsupported_semantic",
        "ambiguous_target",
    }
    assert all(datetime.fromisoformat(case["asked_at"]).tzinfo for case in cases)
    assert all(case["question"] and case["expected_outcome"] for case in cases)
    assert all(
        case["expected_requests"] if case["expected_outcome"] == "PLANNED" else True
        for case in cases
    )
