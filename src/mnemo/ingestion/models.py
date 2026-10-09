"""Provider- and persistence-independent ingestion result models."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CandidateIngestionOutcome(StrEnum):
    """The durable outcome of processing one extracted candidate."""

    PERSISTED = "PERSISTED"
    NOOP = "NOOP"
    BLOCKED_AMBIGUOUS_ENTITY = "BLOCKED_AMBIGUOUS_ENTITY"
    BLOCKED_ENTITY_TYPE_CONFLICT = "BLOCKED_ENTITY_TYPE_CONFLICT"


class EntityMentionRole(StrEnum):
    """Which unresolved mention prevented candidate ingestion."""

    SUBJECT = "SUBJECT"
    OBJECT = "OBJECT"


class CandidateIngestionResult(BaseModel):
    """Explain the outcome of one candidate without provider/database objects."""

    candidate_index: int = Field(ge=0)
    outcome: CandidateIngestionOutcome
    reason: str = Field(min_length=1)
    memory_id: UUID | None = None
    blocked_mention: str | None = None
    blocked_role: EntityMentionRole | None = None
    ambiguous_entity_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> CandidateIngestionResult:
        blocked = self.outcome in {
            CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY,
            CandidateIngestionOutcome.BLOCKED_ENTITY_TYPE_CONFLICT,
        }
        if blocked:
            if self.blocked_mention is None or self.blocked_role is None:
                raise ValueError("blocked outcomes require a mention and role")
        elif self.blocked_mention is not None or self.blocked_role is not None:
            raise ValueError("non-blocked outcomes cannot include a blocked mention or role")
        if self.outcome == CandidateIngestionOutcome.PERSISTED:
            if self.memory_id is None:
                raise ValueError("PERSISTED requires memory_id")
        elif self.memory_id is not None:
            raise ValueError("only PERSISTED may include memory_id")
        if self.outcome == CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY:
            if len(self.ambiguous_entity_ids) < 2:
                raise ValueError("ambiguous outcomes require at least two entity ids")
        elif self.ambiguous_entity_ids:
            raise ValueError("only ambiguous outcomes may include ambiguous entity ids")
        return self


class IngestionResult(BaseModel):
    """Result for one durably stored capture and all extracted candidates."""

    capture_id: UUID
    candidate_results: tuple[CandidateIngestionResult, ...] = ()
