"""Deterministic structured and temporal recall orchestration."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from uuid import UUID

from mnemo.interfaces.clock import Clock
from mnemo.interfaces.entities import EntityResolutionOutcome, EntityResolver
from mnemo.interfaces.queries import MemoryQuery, MemoryQueryOrder, MemoryQueryRepository
from mnemo.models._shared import require_timezone_aware
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.recall.models import (
    RecallMode,
    RecallOutcome,
    StructuredRecallRequest,
    StructuredRecallResult,
)


class RecallInvariantError(ValueError):
    """Raised when recall evidence violates a fail-closed invariant."""


class StructuredRecallService:
    """Resolve a subject and return structured evidence without mutation."""

    def __init__(
        self,
        *,
        entity_resolver: EntityResolver,
        memory_query_repository: MemoryQueryRepository,
        clock: Clock,
    ) -> None:
        self._entity_resolver = entity_resolver
        self._memory_query_repository = memory_query_repository
        self._clock = clock

    def recall(self, request: StructuredRecallRequest) -> StructuredRecallResult:
        resolution = self._entity_resolver.resolve(
            user_id=request.user_id,
            mention=request.subject,
        )
        if resolution.outcome == EntityResolutionOutcome.UNMATCHED:
            return self._result(request=request, outcome=RecallOutcome.NOT_FOUND)
        if resolution.outcome == EntityResolutionOutcome.AMBIGUOUS:
            return self._result(
                request=request,
                outcome=RecallOutcome.AMBIGUOUS_SUBJECT,
                ambiguous_subject_ids=tuple(entity.id for entity in resolution.candidates),
            )

        entity = resolution.matched_entity
        if entity is None:
            raise RecallInvariantError("MATCHED resolution omitted its entity")
        if (
            request.expected_subject_type is not None
            and entity.type != request.expected_subject_type
        ):
            return self._result(
                request=request,
                outcome=RecallOutcome.SUBJECT_TYPE_CONFLICT,
                subject_entity_id=entity.id,
            )

        current_mode = request.mode in (RecallMode.CURRENT, RecallMode.ACTIVE)
        validity_required = current_mode or (
            request.mode == RecallMode.LATEST and request.kind == MemoryKind.CURRENT_STATE
        )
        now = (
            require_timezone_aware(self._clock.now(), field_name="clock.now()")
            if validity_required
            else None
        )
        query = MemoryQuery(
            user_id=request.user_id,
            statuses=None if request.mode == RecallMode.HISTORY else (MemoryStatus.ACTIVE,),
            kind=request.kind,
            subject_entity_id=entity.id,
            predicate=request.predicate,
            event_time_from=request.since,
            event_time_until=request.until,
            valid_at=now,
            order=MemoryQueryOrder.EVENT_TIME_DESC,
            limit=(
                2
                if request.mode == RecallMode.LATEST
                and request.kind == MemoryKind.CURRENT_STATE
                else 1
                if request.mode == RecallMode.LATEST
                else request.limit
            ),
        )
        memories = tuple(self._memory_query_repository.query(query))
        self._validate_evidence(request=request, subject_entity_id=entity.id, memories=memories)
        if now is not None:
            memories = tuple(memory for memory in memories if _is_valid_at(memory, now))
        if not memories:
            return self._result(
                request=request,
                outcome=RecallOutcome.NOT_FOUND,
                subject_entity_id=entity.id,
            )
        self._reject_duplicate_current_state_slots(memories)
        if request.mode == RecallMode.LATEST:
            memories = memories[:1]
        return self._result(
            request=request,
            outcome=RecallOutcome.FOUND,
            subject_entity_id=entity.id,
            memories=memories,
        )

    @staticmethod
    def _result(
        *,
        request: StructuredRecallRequest,
        outcome: RecallOutcome,
        subject_entity_id: UUID | None = None,
        ambiguous_subject_ids: tuple[UUID, ...] = (),
        memories: tuple[Memory, ...] = (),
    ) -> StructuredRecallResult:
        return StructuredRecallResult(
            outcome=outcome,
            mode=request.mode,
            kind=request.kind,
            predicate=request.predicate,
            subject_entity_id=subject_entity_id,
            ambiguous_subject_ids=ambiguous_subject_ids,
            memories=memories,
        )

    @staticmethod
    def _validate_evidence(
        *,
        request: StructuredRecallRequest,
        subject_entity_id: UUID,
        memories: tuple[Memory, ...],
    ) -> None:
        for memory in memories:
            if memory.user_id != request.user_id:
                raise RecallInvariantError("memory query returned another user's evidence")
            if memory.subject_entity_id != subject_entity_id:
                raise RecallInvariantError("memory query returned evidence for another subject")
            if request.kind is not None and memory.kind != request.kind:
                raise RecallInvariantError("memory query returned evidence with another kind")
            if request.predicate is not None and memory.predicate != request.predicate:
                raise RecallInvariantError("memory query returned evidence with another predicate")
            if request.mode != RecallMode.HISTORY and memory.status != MemoryStatus.ACTIVE:
                raise RecallInvariantError("non-history recall returned terminal evidence")

    @staticmethod
    def _reject_duplicate_current_state_slots(memories: tuple[Memory, ...]) -> None:
        keys = [memory.memory_key for memory in memories if memory.kind == MemoryKind.CURRENT_STATE]
        if any(count > 1 for count in Counter(keys).values()):
            raise RecallInvariantError("multiple active CURRENT_STATE memories occupy one slot")


def _is_valid_at(memory: Memory, instant: datetime) -> bool:
    if memory.valid_from is not None and memory.valid_from > instant:
        return False
    if memory.valid_until is not None and memory.valid_until < instant:
        return False
    return memory.expires_at is None or memory.expires_at > instant
