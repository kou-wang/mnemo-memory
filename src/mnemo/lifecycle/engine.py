"""Deterministic lifecycle engine for Mnemo memories.

This module is the single place that decides how an incoming
:class:`~mnemo.models.memory.Memory` reconciles against existing active
memories, and whether a status transition is legal. It must remain:

- pure and side-effect free (no mutation of its inputs, no I/O)
- independent of any database or LLM provider
- the only place that encodes memory-kind-specific lifecycle semantics

Per-kind reconciliation behavior:

- ``CURRENT_STATE``: identified by ``memory_key``. At most one ACTIVE
  memory may exist per key. A new value supersedes the previous active
  value; an unchanged value is a no-op.
- ``FACT``: identified by ``(subject_entity_id, predicate)``. At most one
  ACTIVE fact may exist per subject/predicate. A new value is a
  *correction* that supersedes the previous active fact -- the old fact
  is kept (status ``SUPERSEDED``), never deleted, so provenance and
  history are preserved.
- ``PREFERENCE``: multiple preferences may coexist. A new preference
  never replaces an unrelated one; exact duplicates are a no-op and
  everything else appends. Removing a preference is a status transition
  (e.g. to ``DELETED``), not a reconciliation decision.
- ``EVENT``: append-only. Exact duplicate captures (same subject,
  predicate, value, and ``occurred_at``) are a no-op so that a repeated
  identical capture does not blindly create duplicate history; anything
  else appends.
- ``INTENT``: appends like ``EVENT``/``PREFERENCE``. Its lifecycle
  (``ACTIVE -> COMPLETED | CANCELLED | EXPIRED | DELETED``) is handled by
  :meth:`LifecycleEngine.validate_status_transition`, not by reconciliation.

Callers are responsible for actually persisting the resulting status
changes; this engine only decides what *should* happen.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus


class LifecycleAction(StrEnum):
    """The reconciliation outcome for an incoming memory."""

    APPEND = "APPEND"
    SUPERSEDE = "SUPERSEDE"
    NOOP = "NOOP"


class LifecycleDecision(BaseModel):
    """The result of :meth:`LifecycleEngine.reconcile`.

    ``supersede_ids`` names the existing memories that should transition
    to ``MemoryStatus.SUPERSEDED`` (never deleted) when ``action`` is
    ``SUPERSEDE``.
    """

    action: LifecycleAction
    supersede_ids: list[UUID] = Field(default_factory=list)
    reason: str


class LifecycleInvariantError(ValueError):
    """Raised when applying lifecycle rules would violate a domain invariant."""


class LifecycleEngine:
    """Pure domain logic. No database or LLM calls belong here."""

    def reconcile(
        self,
        *,
        existing_active: list[Memory],
        incoming: Memory,
    ) -> LifecycleDecision:
        """Decide how ``incoming`` should be reconciled against the
        caller-supplied ``existing_active`` memories for the same user.

        ``existing_active`` is filtered to ``ACTIVE`` status defensively,
        but callers should generally already be passing only active
        memories for the relevant subject.
        """
        active = [m for m in existing_active if m.status == MemoryStatus.ACTIVE]

        if incoming.kind == MemoryKind.CURRENT_STATE:
            return self._reconcile_current_state(active=active, incoming=incoming)

        if incoming.kind == MemoryKind.FACT:
            return self._reconcile_fact(active=active, incoming=incoming)

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
        """Raise :class:`LifecycleInvariantError` if ``current -> target``
        is not a legal status transition for ``kind``.

        Rules:

        - A status may always transition to itself (idempotent no-op).
        - Terminal statuses (``SUPERSEDED``, ``COMPLETED``, ``CANCELLED``,
          ``EXPIRED``, ``DELETED``) can never transition to a *different*
          status once reached.
        - ``INTENT`` may move from a non-terminal status to ``COMPLETED``,
          ``CANCELLED``, ``EXPIRED``, or ``DELETED``.
        - All other kinds may move from a non-terminal status to
          ``SUPERSEDED``, ``EXPIRED``, or ``DELETED`` (e.g. a ``FACT``
          correction, a ``PREFERENCE`` removal, or an ``EVENT``
          correction). They may not become ``COMPLETED``/``CANCELLED``,
          which are INTENT-only concepts.
        """
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
        return self._reconcile_single_active_slot(
            incoming=incoming,
            same_slot=same_slot,
            empty_reason="No active memory exists for this state slot.",
            noop_reason="Incoming current state matches the active state.",
            supersede_reason="A new value replaces the active value for the same state slot.",
            invariant_message=(
                "CURRENT_STATE invariant violated: multiple active memories share one memory_key"
            ),
        )

    def _reconcile_fact(
        self,
        *,
        active: list[Memory],
        incoming: Memory,
    ) -> LifecycleDecision:
        """FACT correction semantics: at most one ACTIVE fact may exist
        per ``(subject_entity_id, predicate)``. A differing value is
        treated as a correction that supersedes -- not deletes -- the
        previous active fact, preserving its provenance and history.
        """
        same_slot = [
            m
            for m in active
            if m.kind == MemoryKind.FACT
            and m.subject_entity_id == incoming.subject_entity_id
            and m.predicate == incoming.predicate
        ]
        return self._reconcile_single_active_slot(
            incoming=incoming,
            same_slot=same_slot,
            empty_reason="No active fact exists for this subject and predicate.",
            noop_reason="Incoming fact matches the active fact.",
            supersede_reason=(
                "A corrected fact value supersedes the previous active fact "
                "while preserving its history."
            ),
            invariant_message=(
                "FACT invariant violated: multiple active facts share the same "
                "subject and predicate"
            ),
        )

    @staticmethod
    def _reconcile_single_active_slot(
        *,
        incoming: Memory,
        same_slot: list[Memory],
        empty_reason: str,
        noop_reason: str,
        supersede_reason: str,
        invariant_message: str,
    ) -> LifecycleDecision:
        """Shared reconciliation for "at most one ACTIVE memory per slot"
        kinds (``CURRENT_STATE`` and ``FACT``): append when the slot is
        empty, no-op when the value is unchanged, otherwise supersede the
        single existing occupant of the slot.
        """
        if len(same_slot) > 1:
            raise LifecycleInvariantError(invariant_message)

        if not same_slot:
            return LifecycleDecision(action=LifecycleAction.APPEND, reason=empty_reason)

        current = same_slot[0]
        if current.value == incoming.value:
            return LifecycleDecision(action=LifecycleAction.NOOP, reason=noop_reason)

        return LifecycleDecision(
            action=LifecycleAction.SUPERSEDE,
            supersede_ids=[current.id],
            reason=supersede_reason,
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
