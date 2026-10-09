"""Provider-independent natural-language recall planning boundary."""

from datetime import datetime
from typing import Protocol

from mnemo.recall.models import RecallPlan


class RecallPlanner(Protocol):
    """Interpret a question into structured recall intent only.

    Implementations have no repository, identity-resolution, retrieval,
    lifecycle, persistence, or answer-synthesis authority.
    """

    def plan(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallPlan: ...
