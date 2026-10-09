"""Strict provider-local DTOs for OpenAI Structured Outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.models.candidate import CandidateMemory
from mnemo.models.entity import EntityType
from mnemo.models.types import MemoryKind


class _OpenAISchema(BaseModel):
    """Reject provider fields that are not part of the extraction contract."""

    model_config = ConfigDict(extra="forbid")


class TextValue(_OpenAISchema):
    kind: Literal["text"]
    value: str


class IntegerValue(_OpenAISchema):
    kind: Literal["integer"]
    value: int


class NumberValue(_OpenAISchema):
    kind: Literal["number"]
    value: float


class BooleanValue(_OpenAISchema):
    kind: Literal["boolean"]
    value: bool


class NullValue(_OpenAISchema):
    kind: Literal["null"]


class ListValue(_OpenAISchema):
    kind: Literal["list"]
    value: list[OpenAIValue]


class ObjectField(_OpenAISchema):
    name: str = Field(min_length=1)
    value: OpenAIValue

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return require_non_blank(value, field_name="name")


class ObjectValue(_OpenAISchema):
    kind: Literal["object"]
    value: list[ObjectField]

    @model_validator(mode="after")
    def _require_unique_field_names(self) -> ObjectValue:
        names = [field.name for field in self.value]
        if len(names) != len(set(names)):
            raise ValueError("object value field names must be unique")
        return self


OpenAIValue: TypeAlias = (
    TextValue | IntegerValue | NumberValue | BooleanValue | NullValue | ListValue | ObjectValue
)


class OpenAIExtractedCandidate(_OpenAISchema):
    """A provider result without domain authority or SDK-specific values."""

    kind: MemoryKind
    category: str | None
    subject: str = Field(min_length=1)
    subject_type: EntityType
    predicate: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    object: str | None
    object_type: EntityType | None
    value: OpenAIValue
    occurred_at: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    expires_at: datetime | None

    @field_validator("subject")
    @classmethod
    def _validate_subject(cls, value: str) -> str:
        return require_non_blank(value, field_name="subject")

    @field_validator("category", "object")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name=info.field_name or "text field")

    @field_validator("occurred_at", "valid_from", "valid_until", "expires_at")
    @classmethod
    def _validate_datetime(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        if value is None:
            return None
        return require_timezone_aware(value, field_name=info.field_name or "datetime field")

    @model_validator(mode="after")
    def _validate_object_type(self) -> OpenAIExtractedCandidate:
        if self.object is None and self.object_type is not None:
            raise ValueError("object_type must be None when object is None")
        if self.object is not None and self.object_type is None:
            raise ValueError("object_type is required when object is present")
        return self

    def to_candidate(self) -> CandidateMemory:
        """Map the provider DTO into the provider-independent domain model."""
        return CandidateMemory(
            kind=self.kind,
            category=self.category,
            subject=self.subject,
            subject_type=self.subject_type,
            predicate=self.predicate,
            object=self.object,
            object_type=self.object_type,
            value=_to_json_value(self.value),
            occurred_at=self.occurred_at,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            expires_at=self.expires_at,
        )


class OpenAIExtractionBatch(_OpenAISchema):
    """Top-level response envelope parsed by the OpenAI SDK."""

    candidates: list[OpenAIExtractedCandidate]


def _to_json_value(value: OpenAIValue) -> object:
    if isinstance(value, NullValue):
        return None
    if isinstance(value, ListValue):
        return [_to_json_value(item) for item in value.value]
    if isinstance(value, ObjectValue):
        return {field.name: _to_json_value(field.value) for field in value.value}
    return value.value
