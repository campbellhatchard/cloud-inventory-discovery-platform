"""report output formatting and publication history dismissal

Revision ID: b72e1f8c5d21
Revises: a61d9e7c4b10
Create Date: 2026-08-01 21:30:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b72e1f8c5d21"
down_revision: Union[str, None] = "a61d9e7c4b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROPRIETARY_FOOTER = (
    "This document is the property of and proprietary to Cloud Inventory and contains trade secret and "
    "confidential information, and is solely for the Customer's internal use. Without the express written "
    "consent of Cloud Inventory, this document shall not be used, reproduced, copied, disclosed, or transmitted, "
    "in whole or in part. Copyright Cloud Inventory. All rights reserved."
)


def upgrade() -> None:
    with op.batch_alter_table("publications") as batch_op:
        batch_op.add_column(sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("dismissed_by", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_publications_dismissed_by_users",
            "users",
            ["dismissed_by"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE branding_profiles "
            "SET footer_text = :footer "
            "WHERE footer_text = 'Cloud Inventory | Confidential'"
        ),
        {"footer": PROPRIETARY_FOOTER},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE branding_profiles "
            "SET footer_text = 'Cloud Inventory | Confidential' "
            "WHERE footer_text = :footer"
        ),
        {"footer": PROPRIETARY_FOOTER},
    )

    with op.batch_alter_table("publications") as batch_op:
        batch_op.drop_constraint("fk_publications_dismissed_by_users", type_="foreignkey")
        batch_op.drop_column("dismissed_by")
        batch_op.drop_column("dismissed_at")
