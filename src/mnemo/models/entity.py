"""Entity model: the subject/object of memories (a person, place, object...).

Entity resolution is intentionally conservative elsewhere in the engine
(duplicate entities are preferred over incorrect merges); this module only
validates the shape of an individual entity record.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from mnemo.models._shared import require_non_blank


class EntityType(StrEnum):
    """The kind of real-world thing an :class:`Entity` represents."""

    PERSON = "person"
    PLACE = "place"
    OBJECT = "object"
    ACTIVITY = "activity"
    VEHICLE = "vehicle"
    ORGANIZATION = "organization"
    OTHER = "other"


class Entity(BaseModel):
    """A resolved subject or object referenced by memories.

    ``canonical_name`` is the preferred display name; ``aliases`` holds
    alternative names observed in captures (e.g. nicknames). Aliases are
    deduplicated and blank entries are rejected, but no similarity-based
    merging happens here -- merging ambiguous entities is a deliberate,
    explainable, and reversible decision made outside this model.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: str
    type: EntityType
    canonical_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    @field_validator("canonical_name")
    @classmethod
    def _validate_canonical_name(cls, value: str) -> str:
        return require_non_blank(value, field_name="canonical_name")

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for alias in value:
            cleaned = require_non_blank(alias, field_name="alias")
            if cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)
        return normalized
