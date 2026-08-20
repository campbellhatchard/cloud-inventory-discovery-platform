"""Case-insensitive username authentication

Revision ID: m83j6e2h0f43
Revises: l72i5d1g9e32
Create Date: 2026-08-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "m83j6e2h0f43"
down_revision = "l72i5d1g9e32"
branch_labels = None
depends_on = None


def _normalized(value: str) -> str:
    return value.strip().casefold()


def upgrade() -> None:
    bind = op.get_bind()
    existing = list(bind.execute(sa.text("SELECT id, username FROM users")).mappings())
    seen: dict[str, str] = {}
    normalized_rows: list[tuple[str, str]] = []
    for row in existing:
        username = str(row["username"] or "")
        username_key = _normalized(username)
        if not username_key:
            raise RuntimeError(f"User {row['id']} has an empty username after normalization.")
        if len(username_key) > 500:
            raise RuntimeError(f"Username for user {row['id']} exceeds the normalized username limit.")
        prior = seen.get(username_key)
        if prior is not None:
            raise RuntimeError(
                "Case-insensitive username collision detected between "
                f"user IDs {prior} and {row['id']}. Resolve the duplicate usernames before deploying v0.8.8."
            )
        seen[username_key] = str(row["id"])
        normalized_rows.append((str(row["id"]), username_key))

    op.add_column("users", sa.Column("username_key", sa.String(length=500), nullable=True))
    for user_id, username_key in normalized_rows:
        bind.execute(
            sa.text("UPDATE users SET username_key = :username_key WHERE id = :user_id"),
            {"username_key": username_key, "user_id": user_id},
        )

    with op.batch_alter_table("users") as batch:
        batch.alter_column("username_key", existing_type=sa.String(length=500), nullable=False)
        batch.create_index("ix_users_username_key", ["username_key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_username_key")
        batch.drop_column("username_key")
