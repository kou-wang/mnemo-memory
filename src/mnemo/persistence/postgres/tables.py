"""SQLAlchemy-only PostgreSQL table mappings."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Metadata root used by Alembic; never exposed as a domain model."""


class CaptureRow(Base):
    __tablename__ = "captures"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_captures_user_id_id"),
        Index("ix_captures_user_captured_at", "user_id", "captured_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class EntityRow(Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_entities_user_id_id"),
        Index("ix_entities_user_id", "user_id"),
        Index("ix_entities_user_canonical_name", "user_id", "canonical_name"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)


class MemoryRow(Base):
    __tablename__ = "memories"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_memories_user_id_id"),
        CheckConstraint(
            "(kind = 'CURRENT_STATE' AND memory_key IS NOT NULL) OR "
            "(kind <> 'CURRENT_STATE' AND memory_key IS NULL)",
            name="ck_memories_current_state_memory_key",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_memories_valid_window",
        ),
        CheckConstraint(
            "expires_at IS NULL OR valid_from IS NULL OR expires_at >= valid_from",
            name="ck_memories_expiration_window",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_memories_confidence",
        ),
        ForeignKeyConstraint(
            ["user_id", "subject_entity_id"],
            ["entities.user_id", "entities.id"],
            name="fk_memories_subject_entity_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["user_id", "object_entity_id"],
            ["entities.user_id", "entities.id"],
            name="fk_memories_object_entity_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["user_id", "source_capture_id"],
            ["captures.user_id", "captures.id"],
            name="fk_memories_source_capture_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["user_id", "superseded_by_id"],
            ["memories.user_id", "memories.id"],
            name="fk_memories_superseded_by_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_memories_user_observed_at", "user_id", "observed_at"),
        Index("ix_memories_user_status", "user_id", "status"),
        Index(
            "uq_memories_active_current_state_slot",
            "user_id",
            "memory_key",
            unique=True,
            postgresql_where=text("kind = 'CURRENT_STATE' AND status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    subject_entity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    object_entity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    value: Mapped[Any] = mapped_column(JSONB(none_as_null=False), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    memory_key: Mapped[str | None] = mapped_column(Text)
    superseded_by_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    source_capture_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
