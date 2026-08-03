"""Cloud Inventory solution intelligence and source-aware capability mappings

Revision ID: d94a7b3e1c44
Revises: c83f2a9d6e32
Create Date: 2026-08-03 19:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d94a7b3e1c44"
down_revision: Union[str, None] = "c83f2a9d6e32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("capability_mappings") as batch_op:
        batch_op.alter_column("finding_id", existing_type=sa.String(length=36), nullable=True)
        batch_op.add_column(sa.Column("section_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source_ref", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("source_type", sa.String(length=40), nullable=False, server_default="FINDING"))
        batch_op.add_column(sa.Column("source_label", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("source_statement", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_suggestion_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_capability_mappings_section_id_report_sections",
            "report_sections",
            ["section_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_capability_mappings_ai_suggestion_id_ai_suggestions",
            "ai_suggestions",
            ["ai_suggestion_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_capability_mappings_section_id", ["section_id"], unique=False)
        batch_op.create_index("ix_capability_mappings_source_ref", ["source_ref"], unique=False)
        batch_op.create_index("ix_capability_mappings_ai_suggestion_id", ["ai_suggestion_id"], unique=False)

    # Preserve provenance for every pre-v0.7.0 mapping. The correlated
    # subqueries work on both SQLite test environments and Render PostgreSQL.
    op.execute(
        sa.text(
            """
            UPDATE capability_mappings
            SET section_id = (SELECT section_id FROM findings WHERE findings.id = capability_mappings.finding_id),
                source_ref = 'finding:' || finding_id,
                source_type = 'FINDING',
                source_label = (SELECT CASE finding_type
                    WHEN 'OBSERVATION' THEN 'Observation'
                    WHEN 'PAIN_POINT' THEN 'Pain Point'
                    WHEN 'RISK' THEN 'Risk'
                    WHEN 'GAP' THEN 'Gap'
                    WHEN 'STRENGTH' THEN 'Strength'
                    WHEN 'OPPORTUNITY' THEN 'Opportunity'
                    ELSE replace(finding_type, '_', ' ')
                END FROM findings WHERE findings.id = capability_mappings.finding_id),
                source_statement = (SELECT statement FROM findings WHERE findings.id = capability_mappings.finding_id)
            WHERE finding_id IS NOT NULL
            """
        )
    )

    with op.batch_alter_table("capability_mappings") as batch_op:
        batch_op.alter_column("source_type", existing_type=sa.String(length=40), server_default=None)


def downgrade() -> None:
    # General-note mappings cannot be represented by the v0.6.1 schema. Remove
    # only those source-aware mappings before restoring finding_id NOT NULL.
    op.execute(sa.text("DELETE FROM capability_mappings WHERE finding_id IS NULL"))
    with op.batch_alter_table("capability_mappings") as batch_op:
        batch_op.drop_index("ix_capability_mappings_ai_suggestion_id")
        batch_op.drop_index("ix_capability_mappings_source_ref")
        batch_op.drop_index("ix_capability_mappings_section_id")
        batch_op.drop_constraint("fk_capability_mappings_ai_suggestion_id_ai_suggestions", type_="foreignkey")
        batch_op.drop_constraint("fk_capability_mappings_section_id_report_sections", type_="foreignkey")
        batch_op.drop_column("ai_suggestion_id")
        batch_op.drop_column("source_statement")
        batch_op.drop_column("source_label")
        batch_op.drop_column("source_type")
        batch_op.drop_column("source_ref")
        batch_op.drop_column("section_id")
        batch_op.alter_column("finding_id", existing_type=sa.String(length=36), nullable=False)
