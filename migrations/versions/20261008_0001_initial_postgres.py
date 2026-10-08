"""Create capture, entity, and memory persistence tables.

Revision ID: 20261008_0001
Revises: None
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261008_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "captures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("captured_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_captures"),
        sa.UniqueConstraint("user_id", "id", name="uq_captures_user_id_id"),
    )
    op.create_index(
        "ix_captures_user_captured_at",
        "captures",
        ["user_id", "captured_at"],
    )

    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_entities"),
        sa.UniqueConstraint("user_id", "id", name="uq_entities_user_id_id"),
    )
    op.create_index("ix_entities_user_id", "entities", ["user_id"])
    op.create_index(
        "ix_entities_user_canonical_name",
        "entities",
        ["user_id", "canonical_name"],
    )

    op.create_table(
        "memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("subject_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("object_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("value", postgresql.JSONB(none_as_null=False), nullable=False),
        sa.Column("observed_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("occurred_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("valid_from", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("valid_until", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("memory_key", sa.Text(), nullable=True),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_capture_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_memories_confidence",
        ),
        sa.CheckConstraint(
            "(kind = 'CURRENT_STATE' AND memory_key IS NOT NULL) OR "
            "(kind <> 'CURRENT_STATE' AND memory_key IS NULL)",
            name="ck_memories_current_state_memory_key",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR valid_from IS NULL OR expires_at >= valid_from",
            name="ck_memories_expiration_window",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_memories_valid_window",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "object_entity_id"],
            ["entities.user_id", "entities.id"],
            name="fk_memories_object_entity_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "source_capture_id"],
            ["captures.user_id", "captures.id"],
            name="fk_memories_source_capture_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "subject_entity_id"],
            ["entities.user_id", "entities.id"],
            name="fk_memories_subject_entity_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "superseded_by_id"],
            ["memories.user_id", "memories.id"],
            name="fk_memories_superseded_by_same_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memories"),
        sa.UniqueConstraint("user_id", "id", name="uq_memories_user_id_id"),
    )
    op.create_index(
        "ix_memories_user_observed_at",
        "memories",
        ["user_id", "observed_at"],
    )
    op.create_index("ix_memories_user_status", "memories", ["user_id", "status"])
    op.create_index(
        "uq_memories_active_current_state_slot",
        "memories",
        ["user_id", "memory_key"],
        unique=True,
        postgresql_where=sa.text("kind = 'CURRENT_STATE' AND status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_table("memories")
    op.drop_table("entities")
    op.drop_table("captures")
