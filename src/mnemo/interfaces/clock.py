"""Injectable time source for deterministic temporal logic."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Return the current timezone-aware datetime.

    Implementations must never return a naive datetime.
    """

    def now(self) -> datetime: ...
