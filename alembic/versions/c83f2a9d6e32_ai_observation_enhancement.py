"""AI observation enhancement, source versioning, and photo observation cache

Revision ID: c83f2a9d6e32
Revises: b72e1f8c5d21
Create Date: 2026-08-03 16:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c83f2a9d6e32"
down_revision: Union[str, None] = "b72e1f8c5d21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_jobs") as batch_op:
        batch_op.add_column(sa.Column("context_snapshot", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("parent_suggestion_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_ai_jobs_parent_suggestion_id", ["parent_suggestion_id"], unique=False)

    op.create_table(
        "section_content_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("ai_suggestion_id", sa.String(length=36), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ai_suggestion_id"], ["ai_suggestions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["report_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "content_type", "version"),
    )
    op.create_index("ix_section_content_versions_report_id", "section_content_versions", ["report_id"], unique=False)
    op.create_index("ix_section_content_versions_section_id", "section_content_versions", ["section_id"], unique=False)
    op.create_index("ix_section_content_versions_is_current", "section_content_versions", ["is_current"], unique=False)

    op.create_table(
        "evidence_ai_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("source_file_sha256", sa.String(length=64), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["report_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id"),
    )
    op.create_index("ix_evidence_ai_observations_evidence_id", "evidence_ai_observations", ["evidence_id"], unique=False)
    op.create_index("ix_evidence_ai_observations_report_id", "evidence_ai_observations", ["report_id"], unique=False)
    op.create_index("ix_evidence_ai_observations_section_id", "evidence_ai_observations", ["section_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evidence_ai_observations_section_id", table_name="evidence_ai_observations")
    op.drop_index("ix_evidence_ai_observations_report_id", table_name="evidence_ai_observations")
    op.drop_index("ix_evidence_ai_observations_evidence_id", table_name="evidence_ai_observations")
    op.drop_table("evidence_ai_observations")

    op.drop_index("ix_section_content_versions_is_current", table_name="section_content_versions")
    op.drop_index("ix_section_content_versions_section_id", table_name="section_content_versions")
    op.drop_index("ix_section_content_versions_report_id", table_name="section_content_versions")
    op.drop_table("section_content_versions")

    with op.batch_alter_table("ai_jobs") as batch_op:
        batch_op.drop_index("ix_ai_jobs_parent_suggestion_id")
        batch_op.drop_column("parent_suggestion_id")
        batch_op.drop_column("context_snapshot")
