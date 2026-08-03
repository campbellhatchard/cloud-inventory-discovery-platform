"""targeted benefits and demo orchestration

Revision ID: e05b8c4f2d55
Revises: d94a7b3e1c44
Create Date: 2026-08-03 19:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e05b8c4f2d55"
down_revision: Union[str, None] = "d94a7b3e1c44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("benefits") as batch_op:
        batch_op.add_column(sa.Column("section_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source_ref", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("source_type", sa.String(length=40), nullable=False, server_default="MANUAL"))
        batch_op.add_column(sa.Column("source_label", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("source_statement", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("category", sa.String(length=60), nullable=False, server_default="OPERATIONAL_EFFICIENCY"))
        batch_op.add_column(sa.Column("confidence", sa.String(length=20), nullable=False, server_default="MEDIUM"))
        batch_op.add_column(sa.Column("approved_by", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("ai_suggestion_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_benefits_section_id", "report_sections", ["section_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_benefits_approved_by", "users", ["approved_by"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_benefits_ai_suggestion_id", "ai_suggestions", ["ai_suggestion_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_benefits_section_id", ["section_id"], unique=False)
        batch_op.create_index("ix_benefits_source_ref", ["source_ref"], unique=False)
        batch_op.create_index("ix_benefits_ai_suggestion_id", ["ai_suggestion_id"], unique=False)

    op.create_table(
        "demo_plan_settings",
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("additional_priorities", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("report_id"),
    )

    op.create_table(
        "demo_section_priorities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("priority", sa.String(length=30), nullable=False, server_default="OPTIONAL"),
        sa.Column("user_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("constraints", sa.Text(), nullable=False, server_default=""),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["report_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "section_id"),
    )
    op.create_index("ix_demo_section_priorities_report_id", "demo_section_priorities", ["report_id"], unique=False)
    op.create_index("ix_demo_section_priorities_section_id", "demo_section_priorities", ["section_id"], unique=False)

    op.create_table(
        "demo_plan_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="AI_ACCEPTED"),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("ai_suggestion_id", sa.String(length=36), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_suggestion_id"], ["ai_suggestions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "version"),
    )
    op.create_index("ix_demo_plan_versions_report_id", "demo_plan_versions", ["report_id"], unique=False)
    op.create_index("ix_demo_plan_versions_ai_suggestion_id", "demo_plan_versions", ["ai_suggestion_id"], unique=False)
    op.create_index("ix_demo_plan_versions_is_current", "demo_plan_versions", ["is_current"], unique=False)

    # Existing benefits are preserved and associated to their finding's section where possible.
    op.execute(
        "UPDATE benefits SET section_id = (SELECT findings.section_id FROM findings WHERE findings.id = benefits.finding_id) "
        "WHERE section_id IS NULL AND finding_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_demo_plan_versions_is_current", table_name="demo_plan_versions")
    op.drop_index("ix_demo_plan_versions_ai_suggestion_id", table_name="demo_plan_versions")
    op.drop_index("ix_demo_plan_versions_report_id", table_name="demo_plan_versions")
    op.drop_table("demo_plan_versions")

    op.drop_index("ix_demo_section_priorities_section_id", table_name="demo_section_priorities")
    op.drop_index("ix_demo_section_priorities_report_id", table_name="demo_section_priorities")
    op.drop_table("demo_section_priorities")
    op.drop_table("demo_plan_settings")

    with op.batch_alter_table("benefits") as batch_op:
        batch_op.drop_index("ix_benefits_ai_suggestion_id")
        batch_op.drop_index("ix_benefits_source_ref")
        batch_op.drop_index("ix_benefits_section_id")
        batch_op.drop_constraint("fk_benefits_ai_suggestion_id", type_="foreignkey")
        batch_op.drop_constraint("fk_benefits_approved_by", type_="foreignkey")
        batch_op.drop_constraint("fk_benefits_section_id", type_="foreignkey")
        batch_op.drop_column("ai_suggestion_id")
        batch_op.drop_column("approved_by")
        batch_op.drop_column("confidence")
        batch_op.drop_column("category")
        batch_op.drop_column("source_statement")
        batch_op.drop_column("source_label")
        batch_op.drop_column("source_type")
        batch_op.drop_column("source_ref")
        batch_op.drop_column("section_id")
