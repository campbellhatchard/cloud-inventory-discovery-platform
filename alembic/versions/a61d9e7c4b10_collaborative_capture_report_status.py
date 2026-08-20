"""collaborative capture and report-level status

Revision ID: a61d9e7c4b10
Revises: f50a7c19d8e2
Create Date: 2026-08-01 20:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a61d9e7c4b10"
down_revision: Union[str, None] = "f50a7c19d8e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Section assignment and workflow status are retired in v0.5.1. Keep a
    # simple ACTIVE/REMOVED lifecycle internally so removal/audit behavior
    # remains backward compatible.
    bind.execute(sa.text("UPDATE report_sections SET assigned_to_user_id = NULL"))
    bind.execute(sa.text("UPDATE report_sections SET state = 'ACTIVE' WHERE state <> 'REMOVED'"))


def downgrade() -> None:
    bind = op.get_bind()
    # Assignment cannot be reconstructed. Restore the previous neutral section
    # state so older application versions can still load the records.
    bind.execute(sa.text("UPDATE report_sections SET state = 'NOT_STARTED' WHERE state = 'ACTIVE'"))
