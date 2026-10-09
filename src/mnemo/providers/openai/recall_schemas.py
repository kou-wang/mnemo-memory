"""Strict provider-local DTOs for OpenAI recall planning."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.models.entity import EntityType
from mnemo.models.types import MemoryKind
from mnemo.recall.models import (
    RecallMode,
    RecallPlan,
    RecallPlanOutcome,
    StructuredRecallRequest,
)


class _OpenAIRecallSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenAIPlannedRecallRequest(_OpenAIRecallSchema):
    """Provider output mapped into one deterministic recall request."""

    subject: str = Field(min_length=1)
    expected_subject_type: EntityType | None
    kind: MemoryKind | None
    predicate: str | None = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    mode: RecallMode
    since: datetime | None
    until: datetime | None
    limit: int = Field(ge=1, le=100)

    @field_validator("subject")
    @classmethod
    def _validate_subject(cls, value: str) -> str:
        return require_non_blank(value, field_name="subject")

    @field_validator("since", "until")
    @classmethod
    def _validate_datetime(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        if value is None:
            return None
        return require_timezone_aware(value, field_name=info.field_name or "datetime field")

    @model_validator(mode="after")
    def _validate_range(self) -> OpenAIPlannedRecallRequest:
        if self.since is not None and self.until is not None and self.until < self.since:
            raise ValueError("until must be greater than or equal to since")
        return self

    def to_request(self, *, user_id: str) -> StructuredRecallRequest:
        return StructuredRecallRequest(
            user_id=user_id,
            subject=self.subject,
            expected_subject_type=self.expected_subject_type,
            kind=self.kind,
            predicate=self.predicate,
            mode=self.mode,
            since=self.since,
            until=self.until,
            limit=self.limit,
        )


class OpenAIRecallPlanOutput(_OpenAIRecallSchema):
    """Strict top-level response envelope for recall planning."""

    outcome: RecallPlanOutcome
    requests: list[OpenAIPlannedRecallRequest]

    @model_validator(mode="after")
    def _validate_outcome_shape(self) -> OpenAIRecallPlanOutput:
        if self.outcome == RecallPlanOutcome.PLANNED and not self.requests:
            raise ValueError("PLANNED requires at least one request")
        if self.outcome != RecallPlanOutcome.PLANNED and self.requests:
            raise ValueError("UNSUPPORTED and AMBIGUOUS cannot contain requests")
        return self

    def to_plan(self, *, user_id: str) -> RecallPlan:
        return RecallPlan(
            outcome=self.outcome,
            requests=tuple(request.to_request(user_id=user_id) for request in self.requests),
        )
