from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    PERSON = "person"
    PLACE = "place"
    OBJECT = "object"
    ACTIVITY = "activity"
    VEHICLE = "vehicle"
    ORGANIZATION = "organization"
    OTHER = "other"


class Entity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    type: EntityType
    canonical_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
