"""Conservative, provider-independent entity-resolution boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from mnemo.models._shared import require_non_blank
from mnemo.models.entity import Entity


class EntityResolutionOutcome(StrEnum):
    """Possible outcomes of resolving one extracted mention."""

    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"


class EntityResolution(BaseModel):
    """Explicit result of resolving a mention within one user's scope.

    ``UNMATCHED`` is a decision that later orchestration may use to create an
    entity; resolution itself never creates or persists one. ``AMBIGUOUS``
    preserves multiple candidates and must never be treated as an auto-merge.
    """

    user_id: str = Field(min_length=1)
    mention: str = Field(min_length=1)
    outcome: EntityResolutionOutcome
    matched_entity: Entity | None = None
    candidates: tuple[Entity, ...] = ()

    @field_validator("user_id", "mention")
    @classmethod
    def _require_non_blank(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, field_name=info.field_name or "text field")

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> EntityResolution:
        entities = (() if self.matched_entity is None else (self.matched_entity,)) + self.candidates
        if any(entity.user_id != self.user_id for entity in entities):
            raise ValueError("resolved entities must belong to the requested user_id")

        if self.outcome == EntityResolutionOutcome.MATCHED:
            if self.matched_entity is None or self.candidates:
                raise ValueError("MATCHED requires one matched_entity and no candidates")
        elif self.outcome == EntityResolutionOutcome.UNMATCHED:
            if self.matched_entity is not None or self.candidates:
                raise ValueError("UNMATCHED cannot contain resolved entities")
        else:
            if self.matched_entity is not None or len(self.candidates) < 2:
                raise ValueError("AMBIGUOUS requires at least two candidates and no matched_entity")
            if len({entity.id for entity in self.candidates}) != len(self.candidates):
                raise ValueError("AMBIGUOUS candidates must identify distinct entities")
        return self


class EntityResolver(Protocol):
    """Resolve one subject/object mention conservatively for a specific user."""

    def resolve(self, *, user_id: str, mention: str) -> EntityResolution: ...
