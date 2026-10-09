"""Provider-independent models for grounded recall answers."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from mnemo.models._shared import require_non_blank
from mnemo.models.memory import Memory
from mnemo.recall.models import RecallExecutionOutcome, RecallExecutionResult

NO_EVIDENCE_MESSAGE = "I don't have that saved."


class SynthesizedAnswer(BaseModel):
    """User-facing wording and the grounded memory ids supporting it."""

    text: str = Field(min_length=1)
    cited_memory_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return require_non_blank(value, field_name="answer text")

    @model_validator(mode="after")
    def _reject_duplicate_citations(self) -> SynthesizedAnswer:
        if len(self.cited_memory_ids) != len(set(self.cited_memory_ids)):
            raise ValueError("cited_memory_ids must not contain duplicates")
        return self


class RecallAnswerOutcome(StrEnum):
    """Outcome of deterministic recall plus optional grounded phrasing."""

    ANSWERED = "ANSWERED"
    PARTIAL = "PARTIAL"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS_PLAN = "AMBIGUOUS_PLAN"
    AMBIGUOUS_SUBJECT = "AMBIGUOUS_SUBJECT"
    SUBJECT_TYPE_CONFLICT = "SUBJECT_TYPE_CONFLICT"


class RecallAnswerResult(BaseModel):
    """Complete recall evidence and its validated user-facing answer, if any."""

    outcome: RecallAnswerOutcome
    text: str | None = None
    cited_memory_ids: tuple[UUID, ...] = ()
    recall_result: RecallExecutionResult

    @property
    def evidence(self) -> tuple[Memory, ...]:
        """Return evidence unchanged in deterministic recall order."""
        return self.recall_result.memories

    @model_validator(mode="after")
    def _validate_shape(self) -> RecallAnswerResult:
        if self.outcome in (RecallAnswerOutcome.ANSWERED, RecallAnswerOutcome.PARTIAL):
            if self.text is None or not self.text.strip():
                raise ValueError("answered results require nonblank text")
            if not self.cited_memory_ids:
                raise ValueError("answered results require at least one citation")
        elif self.cited_memory_ids:
            raise ValueError("non-answered results cannot contain citations")

        if self.outcome == RecallAnswerOutcome.NOT_FOUND:
            if self.text != NO_EVIDENCE_MESSAGE:
                raise ValueError("NOT_FOUND requires the deterministic no-evidence message")
        elif self.outcome not in (
            RecallAnswerOutcome.ANSWERED,
            RecallAnswerOutcome.PARTIAL,
        ) and self.text is not None:
            raise ValueError("abstained results cannot contain answer text")

        expected_recall_outcome = {
            RecallAnswerOutcome.ANSWERED: RecallExecutionOutcome.FOUND,
            RecallAnswerOutcome.PARTIAL: RecallExecutionOutcome.PARTIAL,
            RecallAnswerOutcome.NOT_FOUND: RecallExecutionOutcome.NOT_FOUND,
            RecallAnswerOutcome.UNSUPPORTED: RecallExecutionOutcome.UNSUPPORTED,
            RecallAnswerOutcome.AMBIGUOUS_PLAN: RecallExecutionOutcome.AMBIGUOUS_PLAN,
            RecallAnswerOutcome.AMBIGUOUS_SUBJECT: RecallExecutionOutcome.AMBIGUOUS_SUBJECT,
            RecallAnswerOutcome.SUBJECT_TYPE_CONFLICT: (
                RecallExecutionOutcome.SUBJECT_TYPE_CONFLICT
            ),
        }[self.outcome]
        if self.recall_result.outcome != expected_recall_outcome:
            raise ValueError("answer outcome must match the deterministic recall outcome")
        return self
