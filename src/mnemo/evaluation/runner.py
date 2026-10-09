"""Composition and reporting for deterministic contract evaluation."""

from __future__ import annotations

from collections.abc import Sequence

from mnemo.evaluation.entities import evaluate_entity_resolution
from mnemo.evaluation.grounding import evaluate_grounding
from mnemo.evaluation.lifecycle import evaluate_lifecycle
from mnemo.evaluation.metrics import summarize_results
from mnemo.evaluation.models import (
    EvaluationDomain,
    EvaluationReport,
    EvaluationResult,
)
from mnemo.evaluation.planning import evaluate_recall_planning

_DOMAIN_ORDER = (
    EvaluationDomain.LIFECYCLE,
    EvaluationDomain.ENTITY_RESOLUTION,
    EvaluationDomain.RECALL_PLANNING,
    EvaluationDomain.STRUCTURED_RECALL,
    EvaluationDomain.ANSWER_GROUNDING,
)


def build_report(results: Sequence[EvaluationResult]) -> EvaluationReport:
    all_results = tuple(results)
    summaries = tuple(
        summarize_results(
            domain=domain,
            results=tuple(result for result in all_results if result.domain == domain),
        )
        for domain in _DOMAIN_ORDER
        if any(result.domain == domain for result in all_results)
    )
    return EvaluationReport(summaries=summaries, results=all_results)


def run_core_evaluations() -> EvaluationReport:
    """Run network-free deterministic domains that need no external adapter."""
    results = (
        *evaluate_lifecycle(),
        *evaluate_entity_resolution(),
        *evaluate_recall_planning(),
        *evaluate_grounding(),
    )
    return build_report(results)


def evaluation_exit_code(report: EvaluationReport) -> int:
    """Return a process exit code suitable for a 100% deterministic CI gate."""
    return 0 if report.passed else 1
