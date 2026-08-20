"""AI latency lanes and independent photo intelligence

Revision ID: h38e1f7c5a88
Revises: g27d0e6b4f77
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "h38e1f7c5a88"
down_revision = "g27d0e6b4f77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("queue_name", sa.String(length=30), nullable=False, server_default="STANDARD"))
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
        batch.create_index("ix_jobs_queue_name", ["queue_name"], unique=False)
        batch.create_index("ix_jobs_priority", ["priority"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_priority")
        batch.drop_index("ix_jobs_queue_name")
        batch.drop_column("priority")
        batch.drop_column("queue_name")
