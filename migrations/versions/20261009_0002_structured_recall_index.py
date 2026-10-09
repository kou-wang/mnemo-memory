"""Add the structured recall lookup index.

Revision ID: 20261009_0002
Revises: 20261008_0001
Create Date: 2026-10-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261009_0002"
down_revision: str | None = "20261008_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_memories_structured_recall",
        "memories",
        ["user_id", "subject_entity_id", "kind", "status", "predicate"],
    )


def downgrade() -> None:
    op.drop_index("ix_memories_structured_recall", table_name="memories")
