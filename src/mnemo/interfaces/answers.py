"""Provider-independent grounded answer-synthesis boundary."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from mnemo.models.memory import Memory

if TYPE_CHECKING:
    from mnemo.answers.models import SynthesizedAnswer


class AnswerSynthesizer(Protocol):
    """Phrase supplied memory evidence without retrieving or mutating data."""

    def synthesize(
        self,
        *,
        question: str,
        evidence: tuple[Memory, ...],
        asked_at: datetime,
    ) -> SynthesizedAnswer: ...
