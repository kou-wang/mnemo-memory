"""Provider-independent deterministic evaluation public API."""

from mnemo.evaluation.metrics import classification_metrics, summarize_results
from mnemo.evaluation.models import (
    AnswerGroundingEvaluationCase,
    ClassificationMetrics,
    EntityResolutionEvaluationCase,
    EvaluationCase,
    EvaluationDomain,
    EvaluationReport,
    EvaluationResult,
    EvaluationSummary,
    ExtractionEvaluationCase,
    LifecycleEvaluationCase,
    RecallPlanningEvaluationCase,
    StructuredRecallEvaluationCase,
)
from mnemo.evaluation.runner import build_report, evaluation_exit_code, run_core_evaluations
from mnemo.evaluation.structured_recall import evaluate_structured_recall

__all__ = [
    "AnswerGroundingEvaluationCase",
    "ClassificationMetrics",
    "EntityResolutionEvaluationCase",
    "EvaluationCase",
    "EvaluationDomain",
    "EvaluationReport",
    "EvaluationResult",
    "EvaluationSummary",
    "ExtractionEvaluationCase",
    "LifecycleEvaluationCase",
    "RecallPlanningEvaluationCase",
    "StructuredRecallEvaluationCase",
    "classification_metrics",
    "build_report",
    "evaluate_structured_recall",
    "evaluation_exit_code",
    "run_core_evaluations",
    "summarize_results",
]
