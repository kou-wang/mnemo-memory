"""Strict provider-local DTOs for OpenAI grounded answer synthesis."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mnemo.answers.models import SynthesizedAnswer
from mnemo.models._shared import require_non_blank


class OpenAIAnswerOutput(BaseModel):
    """Strict top-level response envelope for a grounded answer."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    cited_memory_ids: list[UUID] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return require_non_blank(value, field_name="answer text")

    def to_answer(self) -> SynthesizedAnswer:
        return SynthesizedAnswer(
            text=self.text,
            cited_memory_ids=tuple(self.cited_memory_ids),
        )
