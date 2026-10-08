"""Test-layer models for reusable capture and lifecycle scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from mnemo.lifecycle.engine import LifecycleAction
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryStatus


@dataclass(frozen=True)
class StatusTransition:
    """An expected deterministic lifecycle transition for a stored memory."""

    memory_id: UUID
    target: MemoryStatus


@dataclass(frozen=True)
class ScenarioStep:
    """One user capture and the lifecycle effects expected from it.

    A capture may produce zero, one, or many memories. A zero-memory step can
    still drive an explicit lifecycle transition, such as completing an intent.
    """

    source_capture_id: UUID
    text: str
    captured_at: datetime
    memories: tuple[Memory, ...] = ()
    expected_actions: tuple[LifecycleAction, ...] = ()
    transitions: tuple[StatusTransition, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("scenario step text must not be blank")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("scenario captured_at must be timezone-aware")
        if len(self.memories) != len(self.expected_actions):
            raise ValueError("each scenario memory must have one expected lifecycle action")
        for memory in self.memories:
            if memory.source_capture_id != self.source_capture_id:
                raise ValueError("scenario memory source_capture_id must match its capture step")
            if memory.observed_at != self.captured_at:
                raise ValueError("scenario memory observed_at must match its capture step")


@dataclass(frozen=True)
class Scenario:
    """A complete capture sequence and its expected final memory state."""

    name: str
    steps: tuple[ScenarioStep, ...]
    initial_memories: tuple[Memory, ...] = ()
    expected_final_statuses: tuple[tuple[UUID, MemoryStatus], ...] = ()
    expected_historical_ids: tuple[UUID, ...] = ()
    supported_queries: tuple[str, ...] = ()
    expect_invariant_error: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name must not be blank")
        if not self.steps:
            raise ValueError("scenario must contain at least one step")

    @property
    def expected_active_ids(self) -> tuple[UUID, ...]:
        """IDs expected to remain active after the whole sequence."""
        return tuple(
            memory_id
            for memory_id, status in self.expected_final_statuses
            if status == MemoryStatus.ACTIVE
        )
