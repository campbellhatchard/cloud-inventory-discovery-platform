"""Durable AI wording reuse and refinement lineage

Revision ID: i49f2a8d6b99
Revises: h38e1f7c5a88
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "i49f2a8d6b99"
down_revision = "h38e1f7c5a88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_jobs") as batch:
        batch.add_column(sa.Column("source_fingerprint", sa.String(length=64), nullable=True))
        batch.create_index("ix_ai_jobs_source_fingerprint", ["source_fingerprint"], unique=False)

    with op.batch_alter_table("ai_suggestions") as batch:
        batch.add_column(sa.Column("source_fingerprint", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("parent_suggestion_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("base_ai_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("refinement_instruction", sa.Text(), nullable=True))
        batch.add_column(sa.Column("superseded_by_suggestion_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_ai_suggestions_source_fingerprint", ["source_fingerprint"], unique=False)
        batch.create_index("ix_ai_suggestions_parent_suggestion_id", ["parent_suggestion_id"], unique=False)
        batch.create_index(
            "ix_ai_suggestions_superseded_by_suggestion_id",
            ["superseded_by_suggestion_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_suggestions") as batch:
        batch.drop_index("ix_ai_suggestions_superseded_by_suggestion_id")
        batch.drop_index("ix_ai_suggestions_parent_suggestion_id")
        batch.drop_index("ix_ai_suggestions_source_fingerprint")
        batch.drop_column("superseded_by_suggestion_id")
        batch.drop_column("refinement_instruction")
        batch.drop_column("base_ai_text")
        batch.drop_column("parent_suggestion_id")
        batch.drop_column("source_fingerprint")

    with op.batch_alter_table("ai_jobs") as batch:
        batch.drop_index("ix_ai_jobs_source_fingerprint")
        batch.drop_column("source_fingerprint")
