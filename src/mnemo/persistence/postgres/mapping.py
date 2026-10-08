"""Explicit mappings between validated domain models and PostgreSQL rows."""

from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.persistence.postgres.tables import CaptureRow, EntityRow, MemoryRow


def capture_to_row(capture: Capture) -> CaptureRow:
    return CaptureRow(
        id=capture.id,
        user_id=capture.user_id,
        source_type=capture.source_type.value,
        raw_text=capture.raw_text,
        captured_at=capture.captured_at,
        created_at=capture.created_at,
    )


def capture_from_row(row: CaptureRow) -> Capture:
    return Capture(
        id=row.id,
        user_id=row.user_id,
        source_type=SourceType(row.source_type),
        raw_text=row.raw_text,
        captured_at=row.captured_at,
        created_at=row.created_at,
    )


def entity_to_row(entity: Entity) -> EntityRow:
    return EntityRow(
        id=entity.id,
        user_id=entity.user_id,
        type=entity.type.value,
        canonical_name=entity.canonical_name,
        aliases=list(entity.aliases),
    )


def entity_from_row(row: EntityRow) -> Entity:
    return Entity(
        id=row.id,
        user_id=row.user_id,
        type=EntityType(row.type),
        canonical_name=row.canonical_name,
        aliases=list(row.aliases),
    )


def memory_to_row(memory: Memory) -> MemoryRow:
    return MemoryRow(
        id=memory.id,
        user_id=memory.user_id,
        kind=memory.kind.value,
        category=memory.category,
        subject_entity_id=memory.subject_entity_id,
        predicate=memory.predicate,
        object_entity_id=memory.object_entity_id,
        value=memory.value,
        observed_at=memory.observed_at,
        occurred_at=memory.occurred_at,
        valid_from=memory.valid_from,
        valid_until=memory.valid_until,
        expires_at=memory.expires_at,
        status=memory.status.value,
        confidence=memory.confidence,
        memory_key=memory.memory_key,
        superseded_by_id=memory.superseded_by_id,
        source_capture_id=memory.source_capture_id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def memory_from_row(row: MemoryRow) -> Memory:
    return Memory(
        id=row.id,
        user_id=row.user_id,
        kind=MemoryKind(row.kind),
        category=row.category,
        subject_entity_id=row.subject_entity_id,
        predicate=row.predicate,
        object_entity_id=row.object_entity_id,
        value=row.value,
        observed_at=row.observed_at,
        occurred_at=row.occurred_at,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        expires_at=row.expires_at,
        status=MemoryStatus(row.status),
        confidence=row.confidence,
        memory_key=row.memory_key,
        superseded_by_id=row.superseded_by_id,
        source_capture_id=row.source_capture_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
