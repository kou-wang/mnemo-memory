"""Core enums shared by every lifecycle-facing domain model.

These enums define the vocabulary of the memory engine. Do not add a new
``MemoryKind`` without first showing why one of the existing five kinds
cannot represent the use case (see project rules / architecture docs).
"""

from enum import StrEnum


class MemoryKind(StrEnum):
    """The five top-level memory kinds the engine understands.

    - ``FACT``: durable information (e.g. a birthday). Corrections may
      supersede an earlier fact, but history is preserved.
    - ``PREFERENCE``: a like/dislike. Multiple preferences may coexist.
    - ``CURRENT_STATE``: mutable state (e.g. where a car is parked),
      identified by ``memory_key``. At most one ACTIVE memory may exist
      per user + ``memory_key``.
    - ``EVENT``: an append-only historical occurrence (e.g. a workout set).
    - ``INTENT``: something the user wants to do/buy/read/watch/visit.
      Lifecycle: ``ACTIVE -> COMPLETED | CANCELLED | EXPIRED | DELETED``.
    """

    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    CURRENT_STATE = "CURRENT_STATE"
    EVENT = "EVENT"
    INTENT = "INTENT"


class MemoryStatus(StrEnum):
    """Lifecycle status of a persisted :class:`~mnemo.models.memory.Memory`.

    ``SUPERSEDED``, ``COMPLETED``, ``CANCELLED``, ``EXPIRED``, and
    ``DELETED`` are terminal: once reached, a memory cannot transition to
    a different status. See
    :meth:`mnemo.lifecycle.engine.LifecycleEngine.validate_status_transition`
    for the exact rules enforced per :class:`MemoryKind`.
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"
