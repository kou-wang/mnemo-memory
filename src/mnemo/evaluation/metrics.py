"""Exact metrics for deterministic evaluation results."""

from __future__ import annotations

from collections.abc import Sequence

from mnemo.evaluation.models import (
    ClassificationMetrics,
    EvaluationDomain,
    EvaluationResult,
    EvaluationSummary,
)


def summarize_results(
    *,
    domain: EvaluationDomain,
    results: Sequence[EvaluationResult],
) -> EvaluationSummary:
    passed = sum(result.passed for result in results)
    case_count = len(results)
    return EvaluationSummary(
        domain=domain,
        case_count=case_count,
        passed_count=passed,
        failed_count=case_count - passed,
        pass_rate=passed / case_count if case_count else 0.0,
    )


def classification_metrics(
    *,
    true_positives: int,
    false_positives: int,
    false_negatives: int,
) -> ClassificationMetrics:
    if min(true_positives, false_positives, false_negatives) < 0:
        raise ValueError("classification counts must be non-negative")
    precision_denominator = true_positives + false_positives
    recall_denominator = true_positives + false_negatives
    precision = true_positives / precision_denominator if precision_denominator else 0.0
    recall = true_positives / recall_denominator if recall_denominator else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ClassificationMetrics(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
    )
