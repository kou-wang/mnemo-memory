"""Deterministic orchestration from a raw capture to durable memories."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from mnemo.entities.normalization import normalize_entity_name
from mnemo.ingestion.models import (
    CandidateIngestionOutcome,
    CandidateIngestionResult,
    EntityMentionRole,
    IngestionResult,
)
from mnemo.interfaces.clock import Clock
from mnemo.interfaces.entities import (
    EntityResolution,
    EntityResolutionOutcome,
    EntityResolver,
)
from mnemo.interfaces.extraction import Extractor
from mnemo.interfaces.repositories import CaptureRepository, EntityRepository, MemoryRepository
from mnemo.lifecycle.engine import LifecycleAction, LifecycleDecision, LifecycleEngine
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus


class IngestionInvariantError(ValueError):
    """Raised when orchestration receives an unsafe or impossible state."""


@dataclass(frozen=True)
class _ResolvedMention:
    mention: str
    entity_type: EntityType
    role: EntityMentionRole
    resolution: EntityResolution


class IngestionService:
    """Connect extraction, safe entity handling, lifecycle, and persistence.

    Repository methods remain the atomic write boundaries. A capture is committed
    before extraction and intentionally survives later failures. Entities created
    successfully may remain after a later write failure; an equivalent retry can
    resolve and reuse them. The service never destructively rolls back committed
    captures/entities, and current-state replacement stays atomic inside
    ``MemoryRepository.supersede_current_state``.
    """

    def __init__(
        self,
        *,
        extractor: Extractor,
        entity_resolver: EntityResolver,
        capture_repository: CaptureRepository,
        entity_repository: EntityRepository,
        memory_repository: MemoryRepository,
        clock: Clock,
        lifecycle_engine: LifecycleEngine,
    ) -> None:
        self._extractor = extractor
        self._entity_resolver = entity_resolver
        self._captures = capture_repository
        self._entities = entity_repository
        self._memories = memory_repository
        self._clock = clock
        self._lifecycle = lifecycle_engine

    def ingest(self, capture: Capture) -> IngestionResult:
        """Persist ``capture`` first, then ingest each extracted candidate."""
        self._ensure_capture(capture)
        candidates = self._extractor.extract(capture)
        results = tuple(
            self._ingest_candidate(capture=capture, candidate=candidate, index=index)
            for index, candidate in enumerate(candidates)
        )
        return IngestionResult(capture_id=capture.id, candidate_results=results)

    def _ensure_capture(self, capture: Capture) -> None:
        stored = self._captures.get(user_id=capture.user_id, capture_id=capture.id)
        if stored is None:
            self._captures.add(user_id=capture.user_id, capture=capture)
            return
        if stored != capture:
            raise IngestionInvariantError(
                "capture id already exists with different content for this user"
            )

    def _ingest_candidate(
        self,
        *,
        capture: Capture,
        candidate: CandidateMemory,
        index: int,
    ) -> CandidateIngestionResult:
        mentions = self._resolve_mentions(user_id=capture.user_id, candidate=candidate)
        blocked = self._blocked_result(mentions=mentions, candidate_index=index)
        if blocked is not None:
            return blocked

        subject, object_entity = self._materialize_entities(
            user_id=capture.user_id,
            mentions=mentions,
        )
        incoming = self._materialize_memory(
            capture=capture,
            candidate=candidate,
            subject_id=subject.id,
            object_id=None if object_entity is None else object_entity.id,
        )
        existing = self._relevant_active(incoming)
        decision = self._lifecycle.reconcile(
            existing_active=list(existing),
            incoming=incoming,
        )
        return self._apply_decision(
            user_id=capture.user_id,
            candidate_index=index,
            incoming=incoming,
            decision=decision,
        )

    def _resolve_mentions(
        self,
        *,
        user_id: str,
        candidate: CandidateMemory,
    ) -> tuple[_ResolvedMention, ...]:
        subject_resolution = self._entity_resolver.resolve(
            user_id=user_id,
            mention=candidate.subject,
        )
        self._require_resolution_scope(user_id=user_id, resolution=subject_resolution)
        subject = _ResolvedMention(
            mention=candidate.subject,
            entity_type=candidate.subject_type,
            role=EntityMentionRole.SUBJECT,
            resolution=subject_resolution,
        )
        if candidate.object is None:
            return (subject,)
        if candidate.object_type is None:
            raise IngestionInvariantError("object mention is missing its required type")
        object_resolution = self._entity_resolver.resolve(
            user_id=user_id,
            mention=candidate.object,
        )
        self._require_resolution_scope(user_id=user_id, resolution=object_resolution)
        object_mention = _ResolvedMention(
            mention=candidate.object,
            entity_type=candidate.object_type,
            role=EntityMentionRole.OBJECT,
            resolution=object_resolution,
        )
        return subject, object_mention

    @staticmethod
    def _require_resolution_scope(*, user_id: str, resolution: EntityResolution) -> None:
        if resolution.user_id != user_id:
            raise IngestionInvariantError(
                "entity resolver returned a result for a different user scope"
            )

    @staticmethod
    def _blocked_result(
        *,
        mentions: tuple[_ResolvedMention, ...],
        candidate_index: int,
    ) -> CandidateIngestionResult | None:
        for mention in mentions:
            resolution = mention.resolution
            if resolution.outcome == EntityResolutionOutcome.AMBIGUOUS:
                return CandidateIngestionResult(
                    candidate_index=candidate_index,
                    outcome=CandidateIngestionOutcome.BLOCKED_AMBIGUOUS_ENTITY,
                    blocked_mention=mention.mention,
                    blocked_role=mention.role,
                    ambiguous_entity_ids=tuple(entity.id for entity in resolution.candidates),
                    reason=f"{mention.role.value.lower()} entity mention is ambiguous",
                )
            if resolution.outcome == EntityResolutionOutcome.MATCHED:
                matched = resolution.matched_entity
                if matched is None:
                    raise IngestionInvariantError("MATCHED resolution omitted its entity")
                if matched.user_id != resolution.user_id:
                    raise IngestionInvariantError(
                        "entity resolver returned a record from a different user scope"
                    )
                if matched.type != mention.entity_type:
                    return CandidateIngestionResult(
                        candidate_index=candidate_index,
                        outcome=CandidateIngestionOutcome.BLOCKED_ENTITY_TYPE_CONFLICT,
                        blocked_mention=mention.mention,
                        blocked_role=mention.role,
                        reason=(
                            f"{mention.role.value.lower()} entity type conflicts "
                            "with extraction"
                        ),
                    )
        return None

    def _materialize_entities(
        self,
        *,
        user_id: str,
        mentions: tuple[_ResolvedMention, ...],
    ) -> tuple[Entity, Entity | None]:
        materialized: list[Entity] = []
        newly_created: dict[tuple[str, EntityType], Entity] = {}
        for mention in mentions:
            if mention.resolution.outcome == EntityResolutionOutcome.MATCHED:
                matched = mention.resolution.matched_entity
                if matched is None:
                    raise IngestionInvariantError("MATCHED resolution omitted its entity")
                materialized.append(matched)
                continue
            if mention.resolution.outcome != EntityResolutionOutcome.UNMATCHED:
                raise IngestionInvariantError("blocked resolution reached entity creation")

            key = (normalize_entity_name(mention.mention), mention.entity_type)
            entity = newly_created.get(key)
            if entity is None:
                entity = Entity(
                    user_id=user_id,
                    type=mention.entity_type,
                    canonical_name=mention.mention,
                    aliases=[],
                )
                self._entities.add(user_id=user_id, entity=entity)
                newly_created[key] = entity
            materialized.append(entity)

        subject = materialized[0]
        object_entity = materialized[1] if len(materialized) == 2 else None
        return subject, object_entity

    def _materialize_memory(
        self,
        *,
        capture: Capture,
        candidate: CandidateMemory,
        subject_id: UUID,
        object_id: UUID | None,
    ) -> Memory:
        instant = self._clock.now()
        memory_key = (
            Memory.build_memory_key(subject_id, candidate.predicate)
            if candidate.kind == MemoryKind.CURRENT_STATE
            else None
        )
        return Memory(
            user_id=capture.user_id,
            kind=candidate.kind,
            category=candidate.category,
            subject_entity_id=subject_id,
            predicate=candidate.predicate,
            object_entity_id=object_id,
            value=candidate.value,
            observed_at=capture.captured_at,
            occurred_at=candidate.occurred_at,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
            expires_at=candidate.expires_at,
            status=MemoryStatus.ACTIVE,
            confidence=candidate.confidence,
            memory_key=memory_key,
            superseded_by_id=None,
            source_capture_id=capture.id,
            created_at=instant,
            updated_at=instant,
        )

    def _relevant_active(self, incoming: Memory) -> tuple[Memory, ...]:
        if incoming.kind == MemoryKind.CURRENT_STATE:
            return tuple(
                self._memories.list_active(
                    user_id=incoming.user_id,
                    memory_key=incoming.memory_key,
                )
            )
        return tuple(
            self._memories.list_active(
                user_id=incoming.user_id,
                kind=incoming.kind,
                subject_entity_id=incoming.subject_entity_id,
                predicate=incoming.predicate,
            )
        )

    def _apply_decision(
        self,
        *,
        user_id: str,
        candidate_index: int,
        incoming: Memory,
        decision: LifecycleDecision,
    ) -> CandidateIngestionResult:
        if decision.action == LifecycleAction.APPEND:
            self._require_supersede_count(decision=decision, expected=0)
            self._memories.append(user_id=user_id, memory=incoming)
            outcome = CandidateIngestionOutcome.PERSISTED
        elif decision.action == LifecycleAction.NOOP:
            self._require_supersede_count(decision=decision, expected=0)
            return CandidateIngestionResult(
                candidate_index=candidate_index,
                outcome=CandidateIngestionOutcome.NOOP,
                reason=decision.reason,
            )
        elif decision.action == LifecycleAction.SUPERSEDE:
            self._require_supersede_count(decision=decision, expected=1)
            self._memories.supersede_current_state(
                user_id=user_id,
                current_memory_id=decision.supersede_ids[0],
                incoming=incoming,
            )
            outcome = CandidateIngestionOutcome.PERSISTED
        else:
            raise IngestionInvariantError("lifecycle engine returned an unknown action")

        return CandidateIngestionResult(
            candidate_index=candidate_index,
            outcome=outcome,
            memory_id=incoming.id,
            reason=decision.reason,
        )

    @staticmethod
    def _require_supersede_count(*, decision: LifecycleDecision, expected: int) -> None:
        if len(decision.supersede_ids) != expected:
            raise IngestionInvariantError(
                "lifecycle decision contained an impossible supersession shape"
            )
