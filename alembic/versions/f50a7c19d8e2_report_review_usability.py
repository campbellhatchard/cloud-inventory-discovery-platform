"""report review usability and prospect logo

Revision ID: f50a7c19d8e2
Revises: e3b7c1a9d2f4
Create Date: 2026-08-01 18:00:00
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = "f50a7c19d8e2"
down_revision: Union[str, None] = "e3b7c1a9d2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid() -> str:
    return str(uuid.uuid4())


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # Prospect-specific branding.
    op.add_column("prospects", sa.Column("logo_storage_key", sa.Text(), nullable=True))

    # No section or discovery question is mandatory in v0.5.0.
    bind.execute(sa.text("UPDATE section_templates SET required_on_final = false"))
    bind.execute(sa.text("UPDATE report_sections SET required_on_final = false"))
    bind.execute(sa.text("UPDATE prompt_definitions SET required_on_final = false"))

    # Retain historical responses to the generic purpose prompt, but stop presenting it.
    bind.execute(sa.text("UPDATE prompt_definitions SET active = false WHERE process_module IS NULL AND stable_key = 'purpose'"))

    templates = bind.execute(sa.text("SELECT id FROM report_templates WHERE report_type = 'FULL_DISCOVERY'")).scalars().all()
    for template_id in templates:
        existing = bind.execute(
            sa.text("SELECT id FROM section_templates WHERE report_template_id = :template_id AND stable_key = 'general-discussion-points'"),
            {"template_id": template_id},
        ).scalar_one_or_none()
        if existing:
            discussion_template_id = existing
        else:
            bind.execute(sa.text("UPDATE section_templates SET display_order = display_order + 10 WHERE report_template_id = :template_id AND display_order >= 130"), {"template_id": template_id})
            discussion_template_id = _uuid()
            bind.execute(
                sa.text("INSERT INTO section_templates (id, report_template_id, stable_key, title, process_module, display_order, required_on_final, owner_removable) VALUES (:id, :template_id, 'general-discussion-points', 'General Discussion Points', NULL, 130, false, true)"),
                {"id": discussion_template_id, "template_id": template_id},
            )

        reports = bind.execute(
            sa.text("SELECT id, owner_id FROM reports WHERE report_template_id = :template_id AND state NOT IN ('FINALIZED', 'DELETED')"),
            {"template_id": template_id},
        ).all()
        for report_id, owner_id in reports:
            exists = bind.execute(sa.text("SELECT id FROM report_sections WHERE report_id = :report_id AND stable_key = 'general-discussion-points'"), {"report_id": report_id}).scalar_one_or_none()
            if exists:
                continue
            bind.execute(sa.text("UPDATE report_sections SET display_order = display_order + 10 WHERE report_id = :report_id AND display_order >= 130"), {"report_id": report_id})
            bind.execute(
                sa.text("INSERT INTO report_sections (id, report_id, section_template_id, stable_key, title, process_module, display_order, state, required_on_final, removed_reason, narrative, version, created_by, updated_by, assigned_to_user_id, created_at, updated_at) VALUES (:id, :report_id, :template_id, 'general-discussion-points', 'General Discussion Points', NULL, 130, 'NOT_STARTED', false, NULL, '', 1, :owner_id, :owner_id, NULL, :created_at, :updated_at)"),
                {"id": _uuid(), "report_id": report_id, "template_id": discussion_template_id, "owner_id": owner_id, "created_at": now, "updated_at": now},
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM report_sections WHERE stable_key = 'general-discussion-points'"))
    bind.execute(sa.text("UPDATE report_sections SET display_order = display_order - 10 WHERE display_order >= 140"))
    bind.execute(sa.text("DELETE FROM section_templates WHERE stable_key = 'general-discussion-points'"))
    bind.execute(sa.text("UPDATE section_templates SET display_order = display_order - 10 WHERE display_order >= 140"))
    bind.execute(sa.text("UPDATE prompt_definitions SET active = true WHERE process_module IS NULL AND stable_key = 'purpose'"))
    op.drop_column("prospects", "logo_storage_key")
