"""Provider-independent models for deterministic structured recall."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.models.entity import EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind


class RecallMode(StrEnum):
    CURRENT = "CURRENT"
    ACTIVE = "ACTIVE"
    HISTORY = "HISTORY"
    LATEST = "LATEST"


class RecallOutcome(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS_SUBJECT = "AMBIGUOUS_SUBJECT"
    SUBJECT_TYPE_CONFLICT = "SUBJECT_TYPE_CONFLICT"


class RecallPlanOutcome(StrEnum):
    """Whether natural-language recall intent was safely structured."""

    PLANNED = "PLANNED"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"


class StructuredRecallRequest(BaseModel):
    """A structured request; natural-language interpretation is out of scope."""

    user_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    expected_subject_type: EntityType | None = None
    kind: MemoryKind | None = None
    predicate: str | None = None
    mode: RecallMode
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("user_id", "subject")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, field_name=info.field_name or "text field")

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str | None) -> str | None:
        return None if value is None else require_non_blank(value, field_name="predicate")

    @field_validator("since", "until")
    @classmethod
    def _validate_datetime(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        if value is None:
            return None
        return require_timezone_aware(value, field_name=info.field_name or "datetime field")

    @model_validator(mode="after")
    def _validate_range(self) -> StructuredRecallRequest:
        if self.since is not None and self.until is not None and self.until < self.since:
            raise ValueError("until must be greater than or equal to since")
        return self


class RecallPlan(BaseModel):
    """Provider-independent output from natural-language recall planning."""

    outcome: RecallPlanOutcome
    requests: tuple[StructuredRecallRequest, ...] = ()

    @model_validator(mode="after")
    def _validate_outcome_shape(self) -> RecallPlan:
        if self.outcome == RecallPlanOutcome.PLANNED and not self.requests:
            raise ValueError("PLANNED requires at least one structured recall request")
        if self.outcome != RecallPlanOutcome.PLANNED and self.requests:
            raise ValueError("UNSUPPORTED and AMBIGUOUS plans cannot contain requests")
        return self


class RecallExecutionOutcome(StrEnum):
    """Aggregate outcome of planning plus deterministic recall execution."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS_PLAN = "AMBIGUOUS_PLAN"
    AMBIGUOUS_SUBJECT = "AMBIGUOUS_SUBJECT"
    SUBJECT_TYPE_CONFLICT = "SUBJECT_TYPE_CONFLICT"
    PARTIAL = "PARTIAL"


class StructuredRecallResult(BaseModel):
    """Deterministic recall evidence and resolution metadata."""

    outcome: RecallOutcome
    mode: RecallMode
    kind: MemoryKind | None = None
    predicate: str | None = None
    subject_entity_id: UUID | None = None
    ambiguous_subject_ids: tuple[UUID, ...] = ()
    memories: tuple[Memory, ...] = ()

    @model_validator(mode="after")
    def _validate_shape(self) -> StructuredRecallResult:
        if self.outcome == RecallOutcome.FOUND:
            if self.subject_entity_id is None or not self.memories:
                raise ValueError("FOUND requires a subject_entity_id and memory evidence")
            if self.ambiguous_subject_ids:
                raise ValueError("FOUND cannot contain ambiguous subjects")
        elif self.outcome == RecallOutcome.AMBIGUOUS_SUBJECT:
            if len(self.ambiguous_subject_ids) < 2:
                raise ValueError("AMBIGUOUS_SUBJECT requires at least two entity ids")
            if self.subject_entity_id is not None or self.memories:
                raise ValueError("AMBIGUOUS_SUBJECT cannot contain matched evidence")
        elif self.memories or self.ambiguous_subject_ids:
            raise ValueError("non-found results cannot contain evidence or ambiguity candidates")
        return self


class RecallRequestExecution(BaseModel):
    """One planned request and its unmodified deterministic recall result."""

    request: StructuredRecallRequest
    result: StructuredRecallResult


class RecallExecutionResult(BaseModel):
    """Complete grounded output of one natural-language recall execution."""

    outcome: RecallExecutionOutcome
    planner_outcome: RecallPlanOutcome
    executions: tuple[RecallRequestExecution, ...] = ()

    @property
    def memories(self) -> tuple[Memory, ...]:
        """Flatten evidence in request order, preserving each result's order."""
        return tuple(
            memory
            for execution in self.executions
            for memory in execution.result.memories
        )
