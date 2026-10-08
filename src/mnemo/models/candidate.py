"""CandidateMemory: the LLM/extractor-facing output before any persistence.

A ``CandidateMemory`` is produced by probabilistic extraction and is never
written to storage directly. The deterministic lifecycle engine (see
``mnemo.lifecycle.engine``) and persistence adapters decide whether a
candidate becomes a new :class:`~mnemo.models.memory.Memory`, is merged,
or is discarded. Validation here is limited to the shape of the candidate
itself -- it must never perform storage or lifecycle decisions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from mnemo.models._shared import require_non_blank
from mnemo.models.types import MemoryKind


class CandidateMemory(BaseModel):
    """A candidate memory extracted from a single capture.

    One capture may yield zero, one, or many candidates. ``subject`` and
    ``predicate`` are free-text at this stage (entity resolution happens
    later); they must still be non-blank. Temporal fields are optional but,
    when present, must be internally consistent (see
    :meth:`validate_temporal_bounds`).
    """

    kind: MemoryKind
    category: str | None = None
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: Any
    object: str | None = None

    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expires_at: datetime | None = None

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("subject")
    @classmethod
    def _validate_subject(cls, value: str) -> str:
        return require_non_blank(value, field_name="subject")

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str) -> str:
        return require_non_blank(value, field_name="predicate")

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> CandidateMemory:
        """Reject temporally inconsistent candidates.

        - ``valid_until`` must not precede ``valid_from``.
        - ``expires_at`` must not precede ``valid_from`` (a memory cannot
          expire before it becomes valid).
        """
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be greater than or equal to valid_from")
        if self.valid_from and self.expires_at and self.expires_at < self.valid_from:
            raise ValueError("expires_at must be greater than or equal to valid_from")
        return self
