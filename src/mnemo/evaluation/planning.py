"""Typed deterministic fixture evaluation for the recall-planning seed."""

from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files
from typing import Any, cast

from mnemo.evaluation.models import EvaluationResult, RecallPlanningEvaluationCase
from mnemo.recall.models import RecallPlan, RecallPlanOutcome, StructuredRecallRequest

_FIXTURE_USER_ID = "evaluation-user"


def recall_planning_cases() -> tuple[RecallPlanningEvaluationCase, ...]:
    resource = files("mnemo.evaluation.data").joinpath("recall_planning.json")
    raw_cases = cast(list[dict[str, Any]], json.loads(resource.read_text(encoding="utf-8")))
    cases: list[RecallPlanningEvaluationCase] = []
    for raw in raw_cases:
        outcome = RecallPlanOutcome(cast(str, raw["expected_outcome"]))
        requests = tuple(
            StructuredRecallRequest(user_id=_FIXTURE_USER_ID, **request)
            for request in cast(list[dict[str, Any]], raw["expected_requests"])
        )
        expected = RecallPlan(outcome=outcome, requests=requests)
        cases.append(
            RecallPlanningEvaluationCase(
                case_id=cast(str, raw["name"]),
                question=cast(str, raw["question"]),
                asked_at=datetime.fromisoformat(cast(str, raw["asked_at"])),
                expected_plan=expected,
                fixture_plan=expected.model_copy(deep=True),
                tags=("deterministic_fixture", "not_model_accuracy"),
            )
        )
    return tuple(cases)


def evaluate_recall_planning() -> tuple[EvaluationResult, ...]:
    results: list[EvaluationResult] = []
    for case in recall_planning_cases():
        passed = case.fixture_plan == case.expected_plan
        results.append(
            EvaluationResult(
                case_id=case.case_id,
                domain=case.domain,
                passed=passed,
                diagnostic=(
                    None
                    if passed
                    else f"expected {case.expected_plan}, got {case.fixture_plan}"
                ),
            )
        )
    return tuple(results)
