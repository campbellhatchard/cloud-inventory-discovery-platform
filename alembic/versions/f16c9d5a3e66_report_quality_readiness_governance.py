"""report quality readiness and governance

Revision ID: f16c9d5a3e66
Revises: e05b8c4f2d55
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f16c9d5a3e66"
down_revision = "e05b8c4f2d55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_content_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "content_type", "version"),
    )
    op.create_index("ix_report_content_versions_report_id", "report_content_versions", ["report_id"], unique=False)
    op.create_index("ix_report_content_versions_is_current", "report_content_versions", ["is_current"], unique=False)

    op.create_table(
        "worker_heartbeats",
        sa.Column("component", sa.String(length=50), nullable=False),
        sa.Column("app_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("storage_configured", sa.Boolean(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("component"),
    )

    with op.batch_alter_table("capabilities") as batch:
        batch.add_column(sa.Column("product_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_reviewed_by", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_capabilities_last_reviewed_by_users", "users", ["last_reviewed_by"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("knowledge_entries") as batch:
        batch.add_column(sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_reviewed_by", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_knowledge_last_reviewed_by_users", "users", ["last_reviewed_by"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("knowledge_entries") as batch:
        batch.drop_constraint("fk_knowledge_last_reviewed_by_users", type_="foreignkey")
        batch.drop_column("last_reviewed_by")
        batch.drop_column("last_reviewed_at")
        batch.drop_column("expires_at")
        batch.drop_column("review_due_at")

    with op.batch_alter_table("capabilities") as batch:
        batch.drop_constraint("fk_capabilities_last_reviewed_by_users", type_="foreignkey")
        batch.drop_column("last_reviewed_by")
        batch.drop_column("last_reviewed_at")
        batch.drop_column("review_due_at")
        batch.drop_column("product_version")

    op.drop_table("worker_heartbeats")
    op.drop_index("ix_report_content_versions_is_current", table_name="report_content_versions")
    op.drop_index("ix_report_content_versions_report_id", table_name="report_content_versions")
    op.drop_table("report_content_versions")
