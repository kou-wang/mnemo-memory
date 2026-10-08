from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus


class LifecycleAction(StrEnum):
    APPEND = "APPEND"
    SUPERSEDE = "SUPERSEDE"
    NOOP = "NOOP"


class LifecycleDecision(BaseModel):
    action: LifecycleAction
    supersede_ids: list[UUID] = Field(default_factory=list)
    reason: str


class LifecycleInvariantError(ValueError):
    pass


class LifecycleEngine:
    """Pure domain logic. No database or LLM calls belong here."""

    def reconcile(
        self,
        *,
        existing_active: list[Memory],
        incoming: Memory,
    ) -> LifecycleDecision:
        active = [m for m in existing_active if m.status == MemoryStatus.ACTIVE]

        if incoming.kind == MemoryKind.CURRENT_STATE:
            return self._reconcile_current_state(active=active, incoming=incoming)

        if self._is_exact_duplicate(active=active, incoming=incoming):
            return LifecycleDecision(
                action=LifecycleAction.NOOP,
                reason="An equivalent active memory already exists.",
            )

        return LifecycleDecision(
            action=LifecycleAction.APPEND,
            reason=f"{incoming.kind.value} memories append by default.",
        )

    def validate_status_transition(
        self,
        *,
        kind: MemoryKind,
        current: MemoryStatus,
        target: MemoryStatus,
    ) -> None:
        if current == target:
            return

        terminal = {
            MemoryStatus.SUPERSEDED,
            MemoryStatus.COMPLETED,
            MemoryStatus.CANCELLED,
            MemoryStatus.EXPIRED,
            MemoryStatus.DELETED,
        }
        if current in terminal:
            raise LifecycleInvariantError(
                f"Cannot transition terminal status {current} to {target}"
            )

        if kind == MemoryKind.INTENT:
            allowed = {
                MemoryStatus.COMPLETED,
                MemoryStatus.CANCELLED,
                MemoryStatus.EXPIRED,
                MemoryStatus.DELETED,
            }
        else:
            allowed = {
                MemoryStatus.SUPERSEDED,
                MemoryStatus.EXPIRED,
                MemoryStatus.DELETED,
            }

        if target not in allowed:
            raise LifecycleInvariantError(
                f"Invalid {kind.value} transition: {current.value} -> {target.value}"
            )

    def _reconcile_current_state(
        self,
        *,
        active: list[Memory],
        incoming: Memory,
    ) -> LifecycleDecision:
        if not incoming.memory_key:
            raise LifecycleInvariantError("CURRENT_STATE requires memory_key")

        same_slot = [m for m in active if m.memory_key == incoming.memory_key]
        if len(same_slot) > 1:
            raise LifecycleInvariantError(
                "CURRENT_STATE invariant violated: multiple active memories share one memory_key"
            )

        if not same_slot:
            return LifecycleDecision(
                action=LifecycleAction.APPEND,
                reason="No active memory exists for this state slot.",
            )

        current = same_slot[0]
        if current.value == incoming.value:
            return LifecycleDecision(
                action=LifecycleAction.NOOP,
                reason="Incoming current state matches the active state.",
            )

        return LifecycleDecision(
            action=LifecycleAction.SUPERSEDE,
            supersede_ids=[current.id],
            reason="A new value replaces the active value for the same state slot.",
        )

    @staticmethod
    def _is_exact_duplicate(*, active: list[Memory], incoming: Memory) -> bool:
        return any(
            existing.kind == incoming.kind
            and existing.subject_entity_id == incoming.subject_entity_id
            and existing.predicate == incoming.predicate
            and existing.value == incoming.value
            and existing.occurred_at == incoming.occurred_at
            for existing in active
        )
