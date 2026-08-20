"""User lifecycle and role administration

Revision ID: l72i5d1g9e32
Revises: k61h4c0f8d21
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op

revision = "l72i5d1g9e32"
down_revision = "k61h4c0f8d21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # v0.8.6 used DELETED as a soft-delete state. v0.8.7 retires deletion
    # and makes the lifecycle explicit and reversible. Rows remain intact.
    op.execute("UPDATE users SET status = 'INACTIVE' WHERE status = 'DELETED'")


def downgrade() -> None:
    # Recreate the legacy lifecycle representation expected by v0.8.6.
    op.execute("UPDATE users SET status = 'DELETED' WHERE status = 'INACTIVE'")
