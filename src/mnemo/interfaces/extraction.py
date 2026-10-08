"""Provider-independent language extraction boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture


class Extractor(Protocol):
    """Interpret a capture as zero, one, or many candidate memories.

    Implementations interpret language only. They must not persist records or
    make deterministic lifecycle decisions or mutations.
    """

    def extract(self, capture: Capture) -> Sequence[CandidateMemory]: ...
