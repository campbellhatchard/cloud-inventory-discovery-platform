"""queue AI generation

Revision ID: c4ed69d5c7a1
Revises: ab1ec74d40fb
Create Date: 2026-07-31 05:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4ed69d5c7a1"
down_revision: Union[str, None] = "ab1ec74d40fb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_jobs", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_jobs", "instructions")
