"""Provider-independent persistence contracts for core domain records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from mnemo.models.capture import Capture
from mnemo.models.entity import Entity
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus


class RepositoryInvariantError(ValueError):
    """Raised when a repository operation would violate its domain contract."""


class CaptureRepository(Protocol):
    """Persist and retrieve raw captures within an explicit user scope.

    Implementations must reject ``add`` when ``capture.user_id`` differs from
    ``user_id``. ``get`` must never return a capture owned by another user; a
    cross-user lookup is indistinguishable from a missing record.
    """

    def add(self, *, user_id: str, capture: Capture) -> None: ...

    def get(self, *, user_id: str, capture_id: UUID) -> Capture | None: ...


class EntityRepository(Protocol):
    """Persist and read entities within an explicit user scope.

    Implementations must reject ``add`` when ``entity.user_id`` differs from
    ``user_id`` and when an entity with the same id already exists. ``get``
    must make a foreign entity indistinguishable from a missing record, and
    ``list_for_user`` must never return another user's entities.
    """

    def add(self, *, user_id: str, entity: Entity) -> None: ...

    def get(self, *, user_id: str, entity_id: UUID) -> Entity | None: ...

    def list_for_user(self, *, user_id: str) -> Sequence[Entity]: ...


class MemoryRepository(Protocol):
    """Persistence operations required by deterministic lifecycle orchestration.

    Every operation is user-scoped and must fail closed on ownership mismatch.
    A ``NOOP`` lifecycle decision has no corresponding write method and requires
    no persistence mutation.
    """

    def list_active(
        self,
        *,
        user_id: str,
        kind: MemoryKind | None = None,
        subject_entity_id: UUID | None = None,
        predicate: str | None = None,
        memory_key: str | None = None,
    ) -> Sequence[Memory]:
        """Return active memories in ``user_id`` matching all supplied filters."""
        ...

    def get(self, *, user_id: str, memory_id: UUID) -> Memory | None:
        """Return a memory only when it belongs to ``user_id``."""
        ...

    def append(self, *, user_id: str, memory: Memory) -> None:
        """Persist an APPEND result unchanged, including source provenance."""
        ...

    def supersede_current_state(
        self,
        *,
        user_id: str,
        current_memory_id: UUID,
        incoming: Memory,
    ) -> None:
        """Atomically supersede one active current state and insert ``incoming``.

        Implementations must perform ownership, ACTIVE status, CURRENT_STATE
        kind, and equal-memory-key checks in the same transaction as both
        writes. The old memory remains stored as ``SUPERSEDED`` with provenance
        intact and points to ``incoming`` through ``superseded_by_id``.
        """
        ...

    def transition_status(
        self,
        *,
        user_id: str,
        memory_id: UUID,
        expected_status: MemoryStatus,
        target_status: MemoryStatus,
    ) -> None:
        """Atomically apply an explicit non-supersession status transition.

        Implementations must use deterministic lifecycle transition rules and
        fail without mutation when ownership or ``expected_status`` does not
        match. They must reject ``target_status=SUPERSEDED``: CURRENT_STATE
        replacement uses :meth:`supersede_current_state`, and future correction
        semantics require their own replacement-aware atomic operation.
        ``DELETED`` is only for an explicit user/privacy deletion.
        """
        ...
