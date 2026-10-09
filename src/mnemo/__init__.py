"""Mnemo temporal memory engine."""

from mnemo.entities import DeterministicEntityResolver, normalize_entity_name
from mnemo.ingestion import (
    CandidateIngestionOutcome,
    CandidateIngestionResult,
    EntityMentionRole,
    IngestionInvariantError,
    IngestionResult,
    IngestionService,
)
from mnemo.interfaces import (
    CaptureRepository,
    Clock,
    EntityRepository,
    EntityResolution,
    EntityResolutionOutcome,
    EntityResolver,
    Extractor,
    MemoryQuery,
    MemoryQueryOrder,
    MemoryQueryRepository,
    MemoryRepository,
    RecallPlanner,
    RepositoryInvariantError,
)
from mnemo.lifecycle.engine import LifecycleAction, LifecycleDecision, LifecycleEngine
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.recall import (
    RecallInvariantError,
    RecallMode,
    RecallOutcome,
    RecallPlan,
    RecallPlanOutcome,
    StructuredRecallRequest,
    StructuredRecallResult,
    StructuredRecallService,
)

__all__ = [
    "CandidateMemory",
    "CandidateIngestionOutcome",
    "CandidateIngestionResult",
    "Capture",
    "CaptureRepository",
    "Clock",
    "DeterministicEntityResolver",
    "Entity",
    "EntityResolution",
    "EntityResolutionOutcome",
    "EntityRepository",
    "EntityResolver",
    "EntityType",
    "EntityMentionRole",
    "Extractor",
    "IngestionInvariantError",
    "IngestionResult",
    "IngestionService",
    "LifecycleAction",
    "LifecycleDecision",
    "LifecycleEngine",
    "Memory",
    "MemoryKind",
    "MemoryRepository",
    "MemoryQuery",
    "MemoryQueryOrder",
    "MemoryQueryRepository",
    "MemoryStatus",
    "RepositoryInvariantError",
    "RecallInvariantError",
    "RecallMode",
    "RecallOutcome",
    "RecallPlan",
    "RecallPlanner",
    "RecallPlanOutcome",
    "SourceType",
    "StructuredRecallRequest",
    "StructuredRecallResult",
    "StructuredRecallService",
    "normalize_entity_name",
]
