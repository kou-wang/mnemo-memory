"""Provider-independent structured recall case evaluation."""

from __future__ import annotations

from collections.abc import Sequence

from mnemo.evaluation.models import EvaluationResult, StructuredRecallEvaluationCase
from mnemo.recall.service import RecallInvariantError, StructuredRecallService


def evaluate_structured_recall(
    *,
    service: StructuredRecallService,
    cases: Sequence[StructuredRecallEvaluationCase],
) -> tuple[EvaluationResult, ...]:
    results: list[EvaluationResult] = []
    for case in cases:
        try:
            result = service.recall(case.request)
        except RecallInvariantError as error:
            results.append(
                EvaluationResult(
                    case_id=case.case_id,
                    domain=case.domain,
                    passed=False,
                    diagnostic=f"unexpected recall invariant error: {error}",
                )
            )
            continue
        values = tuple(memory.value for memory in result.memories)
        source_ids = tuple(memory.source_capture_id for memory in result.memories)
        failures: list[str] = []
        if result.outcome != case.expected_outcome:
            failures.append(f"expected outcome {case.expected_outcome}, got {result.outcome}")
        if values != case.expected_values:
            failures.append(f"expected values {case.expected_values}, got {values}")
        if source_ids != case.expected_source_capture_ids:
            failures.append(
                f"expected source ids {case.expected_source_capture_ids}, got {source_ids}"
            )
        results.append(
            EvaluationResult(
                case_id=case.case_id,
                domain=case.domain,
                passed=not failures,
                diagnostic="; ".join(failures) if failures else None,
            )
        )
    return tuple(results)
