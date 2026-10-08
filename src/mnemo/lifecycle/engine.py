"""Deterministic lifecycle engine for Mnemo memories.

This module is the single place that decides how an incoming
:class:`~mnemo.models.memory.Memory` reconciles against existing active
memories, and whether a status transition is legal. It must remain:

- pure and side-effect free (no mutation of its inputs, no I/O)
- independent of any database or LLM provider
- the only place that encodes memory-kind-specific lifecycle semantics

User isolation is enforced here, not merely assumed: :meth:`LifecycleEngine.reconcile`
fails closed with :class:`LifecycleInvariantError` if any supplied
existing memory belongs to a different user than the incoming memory.

Per-kind reconciliation behavior:

- ``CURRENT_STATE``: identified by ``memory_key``. At most one ACTIVE
  memory may exist per key. A new value supersedes the previous active
  value; an unchanged value is a no-op.
- ``FACT``: exact duplicates are a no-op; any other incoming fact
  (including one that differs only in value for the same
  ``subject_entity_id``/``predicate``) appends. The engine deliberately
  does **not** supersede a differing fact automatically: it cannot tell
  from ``MemoryKind.FACT`` alone whether a predicate is single-valued
  (e.g. ``birthday``) or naturally multi-valued (e.g. ``has_child``,
  ``owns_pet``, ``phone_number``), and uncertain conflicts must not
  silently retire history. Explicit correction/update semantics are a
  future design that will require the caller to provide an unambiguous,
  deterministic correction signal -- not left to this engine to infer.
- ``PREFERENCE``: multiple preferences may coexist. A new preference
  never replaces an unrelated one; exact duplicates are a no-op and
  everything else appends. Sprint 1 does not implement natural-language
  preference removal; when that lands, it will retire/end a prior
  preference via explicit supersession or validity-window logic, not via
  ``MemoryStatus.DELETED`` (which is reserved for explicit user/privacy
  deletion, never as a stand-in for "no longer true").
- ``EVENT``: append-only. Exact duplicate captures (same subject,
  predicate, object, value, and ``occurred_at``) are a no-op so that a
  repeated identical capture does not blindly create duplicate history;
  anything else appends.
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

        User isolation is enforced here, not merely assumed: every memory
        in ``existing_active`` must share ``incoming.user_id``. A foreign-
        user memory is never silently filtered out -- it is treated as a
        caller bug and raises :class:`LifecycleInvariantError`, because
        user isolation is the highest-priority correctness rule in this
        engine.

        ``existing_active`` is filtered to ``ACTIVE`` status defensively,
        but callers should generally already be passing only active
        memories for the relevant subject.

        Only ``CURRENT_STATE`` has slot-based supersession in Sprint 1.
        Every other kind (``FACT``, ``PREFERENCE``, ``EVENT``, ``INTENT``)
        uses the conservative default: an exact duplicate is a no-op,
        anything else appends. See the module docstring for the rationale
        behind not auto-superseding ``FACT``.
        """
        self._require_same_user(existing_active=existing_active, incoming=incoming)

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
          ``SUPERSEDED``, ``EXPIRED``, or ``DELETED``. They may not
          become ``COMPLETED``/``CANCELLED``, which are INTENT-only
          concepts. Note that this transition being *legal* does not mean
          Sprint 1 code currently triggers it automatically -- e.g.
          reconciliation never requests ``DELETED`` for a ``PREFERENCE``
          just because a newer, different preference was captured.
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

        # Defensive: only existing CURRENT_STATE memories for the same slot
        # may participate, even though memory_key is already restricted to
        # CURRENT_STATE at the model layer.
        same_slot = [
            m
            for m in active
            if m.kind == MemoryKind.CURRENT_STATE and m.memory_key == incoming.memory_key
        ]
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
    def _require_same_user(*, existing_active: list[Memory], incoming: Memory) -> None:
        """Fail closed if any supplied memory belongs to a different user.

        User isolation must never depend on the caller correctly
        filtering by ``user_id`` before calling :meth:`reconcile`; the
        domain layer enforces it directly instead of silently dropping
        foreign-user memories, which could mask a serious caller bug.
        """
        for memory in existing_active:
            if memory.user_id != incoming.user_id:
                raise LifecycleInvariantError(
                    "reconcile() received a memory for a different user_id "
                    f"(expected '{incoming.user_id}', got '{memory.user_id}'); "
                    "existing_active must only contain memories for incoming.user_id"
                )

    @staticmethod
    def _is_exact_duplicate(*, active: list[Memory], incoming: Memory) -> bool:
        return any(
            existing.kind == incoming.kind
            and existing.subject_entity_id == incoming.subject_entity_id
            and existing.predicate == incoming.predicate
            and existing.object_entity_id == incoming.object_entity_id
            and existing.value == incoming.value
            and existing.occurred_at == incoming.occurred_at
            for existing in active
        )
