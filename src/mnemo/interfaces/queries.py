"""Provider-independent query contract for structured memory recall."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus


class MemoryQueryOrder(StrEnum):
    """Stable orderings exposed by the memory read boundary."""

    OBSERVED_AT_ASC = "OBSERVED_AT_ASC"
    OBSERVED_AT_DESC = "OBSERVED_AT_DESC"
    EVENT_TIME_DESC = "EVENT_TIME_DESC"


class MemoryQuery(BaseModel):
    """Typed, user-scoped filters understood by memory query adapters.

    ``event_time_*`` applies to ``occurred_at`` when present and otherwise to
    ``observed_at``. ``valid_at`` excludes records that are not valid at that
    instant; it never changes their persisted status.
    """

    user_id: str = Field(min_length=1)
    statuses: tuple[MemoryStatus, ...] | None = None
    kind: MemoryKind | None = None
    subject_entity_id: UUID | None = None
    predicate: str | None = None
    object_entity_id: UUID | None = None
    occurred_at_from: datetime | None = None
    occurred_at_until: datetime | None = None
    observed_at_from: datetime | None = None
    observed_at_until: datetime | None = None
    event_time_from: datetime | None = None
    event_time_until: datetime | None = None
    valid_at: datetime | None = None
    order: MemoryQueryOrder = MemoryQueryOrder.OBSERVED_AT_DESC
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, value: str) -> str:
        return require_non_blank(value, field_name="user_id")

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str | None) -> str | None:
        return None if value is None else require_non_blank(value, field_name="predicate")

    @field_validator(
        "occurred_at_from",
        "occurred_at_until",
        "observed_at_from",
        "observed_at_until",
        "event_time_from",
        "event_time_until",
        "valid_at",
    )
    @classmethod
    def _validate_datetime(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        if value is None:
            return None
        return require_timezone_aware(value, field_name=info.field_name or "datetime field")

    @model_validator(mode="after")
    def _validate_ranges(self) -> MemoryQuery:
        ranges = (
            (self.occurred_at_from, self.occurred_at_until, "occurred_at"),
            (self.observed_at_from, self.observed_at_until, "observed_at"),
            (self.event_time_from, self.event_time_until, "event_time"),
        )
        for start, end, name in ranges:
            if start is not None and end is not None and end < start:
                raise ValueError(f"{name}_until must be greater than or equal to {name}_from")
        if self.statuses is not None and not self.statuses:
            raise ValueError("statuses must be None or contain at least one status")
        return self


class MemoryQueryRepository(Protocol):
    """Read persisted memories without exposing provider-specific objects."""

    def query(self, query: MemoryQuery) -> Sequence[Memory]:
        """Return only ``query.user_id`` records in the requested stable order."""
        ...
