from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from mnemo.models.types import MemoryKind, MemoryStatus


class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str

    kind: MemoryKind
    category: str | None = None

    subject_entity_id: UUID
    predicate: str = Field(min_length=1)
    object_entity_id: UUID | None = None
    value: Any

    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expires_at: datetime | None = None

    status: MemoryStatus = MemoryStatus.ACTIVE
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    memory_key: str | None = None
    superseded_by_id: UUID | None = None
    source_capture_id: UUID | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> "Memory":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be greater than or equal to valid_from")
        return self

    @staticmethod
    def build_memory_key(subject_entity_id: UUID, predicate: str) -> str:
        return f"{subject_entity_id}:{predicate.strip().lower()}"
