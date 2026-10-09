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
    MemoryRepository,
    RepositoryInvariantError,
)
from mnemo.lifecycle.engine import LifecycleAction, LifecycleDecision, LifecycleEngine
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus

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
    "MemoryStatus",
    "RepositoryInvariantError",
    "SourceType",
    "normalize_entity_name",
]
