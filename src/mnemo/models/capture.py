"""Raw capture model that precedes probabilistic extraction."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from mnemo.models._shared import require_non_blank, require_timezone_aware


class SourceType(StrEnum):
    """How text entered the memory pipeline."""

    TEXT = "TEXT"
    VOICE = "VOICE"


class Capture(BaseModel):
    """A user's raw text capture before extraction.

    Voice captures contain the transcript, not raw audio. Product policy deletes
    raw audio after transcription by default, so audio bytes or locations do not
    belong in this provider-independent domain model.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: str = Field(min_length=1)
    source_type: SourceType
    raw_text: str = Field(min_length=1)
    captured_at: datetime
    created_at: datetime

    @field_validator("user_id", "raw_text")
    @classmethod
    def _require_non_blank(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, field_name=info.field_name or "text field")

    @field_validator("captured_at", "created_at")
    @classmethod
    def _require_timezone_aware(cls, value: datetime, info: ValidationInfo) -> datetime:
        return require_timezone_aware(value, field_name=info.field_name or "datetime field")
