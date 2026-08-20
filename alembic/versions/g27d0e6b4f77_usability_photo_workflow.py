"""usability navigation branding and evidence workflow

Revision ID: g27d0e6b4f77
Revises: f16c9d5a3e66
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "g27d0e6b4f77"
down_revision = "f16c9d5a3e66"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("branding_profiles") as batch:
        batch.add_column(sa.Column("photo_size_uom", sa.String(length=12), nullable=False, server_default="INCHES"))
        batch.add_column(sa.Column("landscape_photo_width", sa.Float(), nullable=False, server_default="6.5"))
        batch.add_column(sa.Column("landscape_photo_height", sa.Float(), nullable=False, server_default="4.25"))
        batch.add_column(sa.Column("portrait_photo_width", sa.Float(), nullable=False, server_default="4.25"))
        batch.add_column(sa.Column("portrait_photo_height", sa.Float(), nullable=False, server_default="6.5"))


def downgrade() -> None:
    with op.batch_alter_table("branding_profiles") as batch:
        batch.drop_column("portrait_photo_height")
        batch.drop_column("portrait_photo_width")
        batch.drop_column("landscape_photo_height")
        batch.drop_column("landscape_photo_width")
        batch.drop_column("photo_size_uom")
