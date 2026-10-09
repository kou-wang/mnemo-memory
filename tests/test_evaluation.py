from __future__ import annotations

import inspect
import json
from typing import cast

import pytest
from pydantic import ValidationError

import mnemo.evaluation.models as evaluation_models
from mnemo.evaluation import (
    EvaluationDomain,
    EvaluationResult,
    StructuredRecallEvaluationCase,
    build_report,
    classification_metrics,
    evaluate_structured_recall,
    evaluation_exit_code,
    run_core_evaluations,
    summarize_results,
)
from mnemo.evaluation.planning import recall_planning_cases
from mnemo.models.types import MemoryKind
from mnemo.recall import RecallMode, RecallOutcome, StructuredRecallRequest
from mnemo.recall.service import RecallInvariantError, StructuredRecallService


def test_core_contract_dataset_passes_completely_and_serializes() -> None:
    report = run_core_evaluations()

    assert report.passed
    assert evaluation_exit_code(report) == 0
    assert sum(summary.case_count for summary in report.summaries) == 42
    assert all(summary.pass_rate == 1.0 for summary in report.summaries)
    assert report.provider_quality_evaluated is False

    payload = json.loads(report.model_dump_json())
    assert payload["schema_version"] == "1"
    assert payload["deterministic_contracts"] is True
    assert payload["provider_quality_evaluated"] is False
    assert len(payload["results"]) == 42


def test_recall_planning_seed_is_packaged_as_typed_harness_cases() -> None:
    cases = recall_planning_cases()

    assert {case.case_id for case in cases} == {
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
    assert all(case.asked_at.tzinfo is not None for case in cases)
    assert all("not_model_accuracy" in case.tags for case in cases)


def test_classification_metrics_include_explicit_zero_denominator_behavior() -> None:
    metrics = classification_metrics(
        true_positives=8,
        false_positives=2,
        false_negatives=4,
    )
    empty = classification_metrics(
        true_positives=0,
        false_positives=0,
        false_negatives=0,
    )

    assert metrics.precision == pytest.approx(0.8)
    assert metrics.recall == pytest.approx(2 / 3)
    assert metrics.f1 == pytest.approx(8 / 11)
    assert (empty.precision, empty.recall, empty.f1) == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="non-negative"):
        classification_metrics(true_positives=-1, false_positives=0, false_negatives=0)


def test_failed_contract_produces_diagnostic_and_nonzero_gate() -> None:
    failed = EvaluationResult(
        case_id="deliberate_failure",
        domain=EvaluationDomain.LIFECYCLE,
        passed=False,
        diagnostic="expected APPEND, got NOOP",
    )
    report = build_report((failed,))

    assert not report.passed
    assert evaluation_exit_code(report) == 1
    assert report.summaries[0].pass_rate == 0.0
    assert report.results[0].diagnostic == "expected APPEND, got NOOP"


def test_pass_rate_handles_partial_and_empty_results() -> None:
    results = (
        EvaluationResult(
            case_id="pass", domain=EvaluationDomain.ENTITY_RESOLUTION, passed=True
        ),
        EvaluationResult(
            case_id="fail",
            domain=EvaluationDomain.ENTITY_RESOLUTION,
            passed=False,
            diagnostic="mismatch",
        ),
    )
    summary = summarize_results(domain=EvaluationDomain.ENTITY_RESOLUTION, results=results)
    empty = summarize_results(domain=EvaluationDomain.ENTITY_RESOLUTION, results=())

    assert summary.case_count == 2
    assert summary.pass_rate == 0.5
    assert empty.pass_rate == 0.0


def test_case_identifiers_are_stable_and_validated() -> None:
    ids = [result.case_id for result in run_core_evaluations().results]

    assert len(ids) == len(set(ids))
    with pytest.raises(ValidationError, match="case_id"):
        StructuredRecallEvaluationCase(
            case_id="Not stable",
            request=_recall_request(),
            expected_outcome=RecallOutcome.NOT_FOUND,
        )


def test_provider_independent_evaluation_models_have_no_adapter_leakage() -> None:
    source = inspect.getsource(evaluation_models)

    for forbidden in ("openai", "sqlalchemy", "psycopg", "Postgres"):
        assert forbidden not in source


def test_structured_recall_case_requires_provenance_for_each_value() -> None:
    with pytest.raises(ValidationError, match="equal lengths"):
        StructuredRecallEvaluationCase(
            case_id="invalid_provenance",
            request=_recall_request(),
            expected_outcome=RecallOutcome.FOUND,
            expected_values=("B7",),
        )


def test_structured_recall_invariant_becomes_failed_result() -> None:
    class BrokenRecall:
        def recall(self, request: StructuredRecallRequest) -> object:
            raise RecallInvariantError("foreign evidence")

    case = StructuredRecallEvaluationCase(
        case_id="fail_closed",
        request=_recall_request(),
        expected_outcome=RecallOutcome.FOUND,
    )

    results = evaluate_structured_recall(
        service=cast(StructuredRecallService, BrokenRecall()),
        cases=(case,),
    )

    assert results[0].passed is False
    assert results[0].diagnostic == "unexpected recall invariant error: foreign evidence"


def _recall_request() -> StructuredRecallRequest:
    return StructuredRecallRequest(
        user_id="evaluation-user",
        subject="my car",
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        mode=RecallMode.CURRENT,
    )
