from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from mnemo.models.types import MemoryKind


class CandidateMemory(BaseModel):
    """LLM-facing representation before persistence decisions are made."""

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
