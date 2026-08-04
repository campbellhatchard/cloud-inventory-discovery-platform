"""Cloud Inventory configuration intelligence

Revision ID: j50g3b9e7c10
Revises: i49f2a8d6b99
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "j50g3b9e7c10"
down_revision = "i49f2a8d6b99"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_entries") as batch:
        batch.add_column(sa.Column("source_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("knowledge_kind", sa.String(length=50), nullable=False, server_default="GENERAL"))
        batch.add_column(sa.Column("structured_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.create_index("ix_knowledge_entries_source_version", ["source_version"], unique=False)
        batch.create_index("ix_knowledge_entries_knowledge_kind", ["knowledge_kind"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("knowledge_entries") as batch:
        batch.drop_index("ix_knowledge_entries_knowledge_kind")
        batch.drop_index("ix_knowledge_entries_source_version")
        batch.drop_column("structured_data")
        batch.drop_column("knowledge_kind")
        batch.drop_column("source_version")
