"""Memory: the persisted, lifecycle-managed record.

A ``Memory`` is what the deterministic lifecycle engine and persistence
adapters operate on. Unlike :class:`~mnemo.models.candidate.CandidateMemory`,
subjects/objects have been resolved to :class:`~mnemo.models.entity.Entity`
identifiers, and ``memory_key`` (when present) identifies a mutable
``CURRENT_STATE`` slot.

This module only validates the shape of a single record (temporal
ordering, ``memory_key`` normalization/requirement). Cross-record
invariants -- e.g. "at most one ACTIVE memory per memory_key" -- are the
responsibility of :mod:`mnemo.lifecycle.engine`, not this model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from mnemo.models._shared import (
    normalize_memory_key,
    require_non_blank,
    require_timezone_aware,
)
from mnemo.models.types import MemoryKind, MemoryStatus


class Memory(BaseModel):
    """A persisted memory record.

    Temporal fields are distinct and must not be conflated:

    - ``observed_at``: when the capture that produced this memory happened.
    - ``occurred_at``: when the underlying real-world event occurred, if
      different from ``observed_at`` (e.g. logging a workout the next day).
    - ``valid_from`` / ``valid_until``: the window during which the memory
      is considered true/active, if bounded.
    - ``expires_at``: when the memory should be treated as stale even if
      no explicit correction has arrived.
    - ``created_at`` / ``updated_at``: storage bookkeeping, never a
      substitute for the above.
    """

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

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str) -> str:
        return require_non_blank(value, field_name="predicate")

    @field_validator("memory_key")
    @classmethod
    def _normalize_memory_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_memory_key(value)

    @field_validator(
        "observed_at",
        "occurred_at",
        "valid_from",
        "valid_until",
        "expires_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def _require_timezone_aware(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        if value is None:
            return None
        return require_timezone_aware(value, field_name=info.field_name or "datetime field")

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> Memory:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be greater than or equal to valid_from")
        if self.valid_from and self.expires_at and self.expires_at < self.valid_from:
            raise ValueError("expires_at must be greater than or equal to valid_from")
        return self

    @model_validator(mode="after")
    def validate_current_state_requires_memory_key(self) -> Memory:
        """Enforce architecture invariants for ``CURRENT_STATE`` memories.

        - A ``memory_key`` identifying the mutable state slot is required.
        - The ``memory_key`` must be exactly the canonical key derived from
          this memory's own ``subject_entity_id`` and ``predicate`` (see
          :meth:`build_memory_key`). Without this check, a caller could
          supply an arbitrary ``memory_key`` that does not describe the
          same subject/predicate, letting a memory get reconciled against
          the wrong state slot.
        """
        if self.kind != MemoryKind.CURRENT_STATE:
            return self

        if self.memory_key is None:
            raise ValueError("CURRENT_STATE memories require a memory_key")

        canonical_key = self.build_memory_key(self.subject_entity_id, self.predicate)
        if self.memory_key != canonical_key:
            raise ValueError(
                "CURRENT_STATE memory_key must equal the canonical key derived from "
                f"subject_entity_id and predicate (expected '{canonical_key}', "
                f"got '{self.memory_key}')"
            )
        return self

    @staticmethod
    def build_memory_key(subject_entity_id: UUID, predicate: str) -> str:
        """Build a normalized ``memory_key`` of the form
        ``<subject_entity_id>:<normalized_predicate>``.
        """
        return normalize_memory_key(f"{subject_entity_id}:{predicate.strip()}")
