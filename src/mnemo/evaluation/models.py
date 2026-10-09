"""Typed, serializable models for deterministic contract evaluation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from mnemo.answers.models import RecallAnswerOutcome, SynthesizedAnswer
from mnemo.interfaces.entities import EntityResolutionOutcome
from mnemo.lifecycle.engine import LifecycleAction
from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.models.candidate import CandidateMemory
from mnemo.models.entity import Entity
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryStatus
from mnemo.recall.models import (
    RecallExecutionResult,
    RecallOutcome,
    RecallPlan,
    StructuredRecallRequest,
)


class EvaluationDomain(StrEnum):
    EXTRACTION = "extraction"
    LIFECYCLE = "lifecycle"
    ENTITY_RESOLUTION = "entity_resolution"
    RECALL_PLANNING = "recall_planning"
    STRUCTURED_RECALL = "structured_recall"
    ANSWER_GROUNDING = "answer_grounding"


class EvaluationCase(BaseModel):
    """Stable identity shared by every typed evaluation case."""

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    domain: EvaluationDomain
    tags: tuple[str, ...] = ()

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(require_non_blank(tag, field_name="tag") for tag in value)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evaluation tags must be unique")
        return cleaned


class ExtractionEvaluationCase(EvaluationCase):
    """Reusable provider-quality extraction label; not a mocked accuracy claim."""

    domain: Literal[EvaluationDomain.EXTRACTION] = EvaluationDomain.EXTRACTION
    raw_text: str
    reference_timestamp: datetime
    expected_candidates: tuple[CandidateMemory, ...]

    @field_validator("raw_text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return require_non_blank(value, field_name="raw_text")

    @field_validator("reference_timestamp")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return require_timezone_aware(value, field_name="reference_timestamp")


class LifecycleEvaluationCase(EvaluationCase):
    domain: Literal[EvaluationDomain.LIFECYCLE] = EvaluationDomain.LIFECYCLE
    existing_active: tuple[Memory, ...] = ()
    incoming: Memory
    expected_action: LifecycleAction | None = None
    expected_supersede_ids: tuple[UUID, ...] = ()
    transition_to: MemoryStatus | None = None
    expect_invariant_error: bool = False

    @model_validator(mode="after")
    def _validate_expectation(self) -> LifecycleEvaluationCase:
        if self.expect_invariant_error == (self.expected_action is not None):
            raise ValueError("case requires exactly one action or invariant-error expectation")
        return self


class EntityResolutionEvaluationCase(EvaluationCase):
    domain: Literal[EvaluationDomain.ENTITY_RESOLUTION] = EvaluationDomain.ENTITY_RESOLUTION
    user_id: str
    mention: str
    entities: tuple[Entity, ...]
    expected_outcome: EntityResolutionOutcome
    expected_entity_ids: tuple[UUID, ...] = ()

    @field_validator("user_id", "mention")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, field_name=info.field_name or "text")


class RecallPlanningEvaluationCase(EvaluationCase):
    domain: Literal[EvaluationDomain.RECALL_PLANNING] = EvaluationDomain.RECALL_PLANNING
    question: str
    asked_at: datetime
    expected_plan: RecallPlan
    fixture_plan: RecallPlan

    @field_validator("question")
    @classmethod
    def _validate_question(cls, value: str) -> str:
        return require_non_blank(value, field_name="question")

    @field_validator("asked_at")
    @classmethod
    def _validate_asked_at(cls, value: datetime) -> datetime:
        return require_timezone_aware(value, field_name="asked_at")


class StructuredRecallEvaluationCase(EvaluationCase):
    domain: Literal[EvaluationDomain.STRUCTURED_RECALL] = EvaluationDomain.STRUCTURED_RECALL
    request: StructuredRecallRequest
    expected_outcome: RecallOutcome
    expected_values: tuple[Any, ...] = ()
    expected_source_capture_ids: tuple[UUID | None, ...] = ()

    @model_validator(mode="after")
    def _validate_expected_evidence(self) -> StructuredRecallEvaluationCase:
        if len(self.expected_values) != len(self.expected_source_capture_ids):
            raise ValueError("expected values and source-capture ids must have equal lengths")
        return self


class AnswerGroundingEvaluationCase(EvaluationCase):
    domain: Literal[EvaluationDomain.ANSWER_GROUNDING] = EvaluationDomain.ANSWER_GROUNDING
    recall_result: RecallExecutionResult
    synthesized_answer: SynthesizedAnswer | None = None
    expected_outcome: RecallAnswerOutcome | None = None
    expect_synthesizer_call: bool
    expect_invariant_error: bool = False

    @model_validator(mode="after")
    def _validate_expectation(self) -> AnswerGroundingEvaluationCase:
        if self.expect_invariant_error == (self.expected_outcome is not None):
            raise ValueError("case requires exactly one outcome or invariant-error expectation")
        return self


class EvaluationResult(BaseModel):
    case_id: str
    domain: EvaluationDomain
    passed: bool
    diagnostic: str | None = None

    @model_validator(mode="after")
    def _validate_diagnostic(self) -> EvaluationResult:
        if self.passed and self.diagnostic is not None:
            raise ValueError("passing evaluation results cannot contain diagnostics")
        if not self.passed and self.diagnostic is None:
            raise ValueError("failed evaluation results require diagnostics")
        return self


class EvaluationSummary(BaseModel):
    domain: EvaluationDomain
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_counts(self) -> EvaluationSummary:
        if self.passed_count + self.failed_count != self.case_count:
            raise ValueError("passed_count + failed_count must equal case_count")
        return self


class ClassificationMetrics(BaseModel):
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)


class EvaluationReport(BaseModel):
    """Serializable deterministic report; it makes no model-accuracy claim."""

    schema_version: str = "1"
    deterministic_contracts: bool = True
    provider_quality_evaluated: bool = False
    summaries: tuple[EvaluationSummary, ...]
    results: tuple[EvaluationResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.summaries) and all(summary.failed_count == 0 for summary in self.summaries)

    def human_summary(self) -> str:
        lines = [
            f"{summary.domain.value}: {summary.pass_rate:.0%} "
            f"({summary.passed_count}/{summary.case_count})"
            for summary in self.summaries
        ]
        lines.append("provider_model_quality: not_run")
        return "\n".join(lines)
