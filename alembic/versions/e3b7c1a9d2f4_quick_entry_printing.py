"""quick entry printing process backfill

Revision ID: e3b7c1a9d2f4
Revises: c4ed69d5c7a1
Create Date: 2026-07-31 13:20:00
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = "e3b7c1a9d2f4"
down_revision: Union[str, None] = "c4ed69d5c7a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROCESS_PROMPTS = [
    (10, "process-purpose", "What is the business purpose of this process?", "LONG_TEXT", "HIGH", True),
    (20, "participants", "Who performs, supervises, or depends on the process?", "LONG_TEXT", "HIGH", True),
    (30, "trigger-inputs", "What triggers the process and what inputs or documents are required?", "LONG_TEXT", "HIGH", True),
    (40, "current-steps", "Describe the current process from start to finish, including decision points.", "LONG_TEXT", "HIGH", True),
    (50, "systems-documents", "Which systems, spreadsheets, forms, labels, and devices are used?", "LONG_TEXT", "HIGH", True),
    (60, "data-captured", "What item, location, lot, serial, quantity, UOM, owner, job, work order, or other data is captured?", "LONG_TEXT", "NORMAL", False),
    (70, "exceptions-workarounds", "What exceptions, manual workarounds, duplicate entry, or off-system records exist?", "LONG_TEXT", "HIGH", True),
    (80, "volumes-service", "What are the volumes, frequencies, peaks, service levels, and staffing requirements?", "LONG_TEXT", "NORMAL", False),
    (90, "controls", "What controls, approvals, validations, or segregation of duties are used?", "LONG_TEXT", "NORMAL", False),
    (100, "pain-points", "What causes delay, error, rework, risk, congestion, inventory inaccuracy, or excessive supervision?", "LONG_TEXT", "HIGH", True),
    (110, "impact", "What is the operational, customer, labor, financial, safety, or compliance impact?", "LONG_TEXT", "HIGH", True),
    (120, "baseline", "What measurable baseline could demonstrate the current performance and future improvement?", "LONG_TEXT", "NORMAL", False),
    (130, "photos", "Capture photographs of the work area, labels, documents, storage method, equipment, or exceptions that support the observation.", "PHOTO", "HIGH", False),
    (140, "future-functionality", "Which approved Cloud Inventory capabilities could address the documented process and pain points?", "LONG_TEXT", "NORMAL", False),
    (150, "future-process", "Describe the proposed future process without making unsupported commitments.", "LONG_TEXT", "NORMAL", False),
    (160, "benefits", "What qualitative benefits and measurable outcomes could result, subject to validation?", "LONG_TEXT", "NORMAL", False),
    (170, "dependencies", "What integration, master data, hardware, infrastructure, change, or policy prerequisites exist?", "LONG_TEXT", "NORMAL", False),
    (180, "confidence", "How confident are you in this assessment and what evidence supports it?", "SELECT", "NORMAL", False),
]


def _uuid() -> str:
    return str(uuid.uuid4())


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    templates = bind.execute(
        sa.text("SELECT id FROM report_templates WHERE report_type = 'FULL_DISCOVERY'")
    ).scalars().all()

    for template_id in templates:
        existing_template_id = bind.execute(
            sa.text(
                "SELECT id FROM section_templates "
                "WHERE report_template_id = :template_id AND stable_key = 'printing'"
            ),
            {"template_id": template_id},
        ).scalar_one_or_none()

        if existing_template_id:
            printing_template_id = existing_template_id
        else:
            bind.execute(
                sa.text(
                    "UPDATE section_templates SET display_order = display_order + 10 "
                    "WHERE report_template_id = :template_id AND display_order >= 220"
                ),
                {"template_id": template_id},
            )
            printing_template_id = _uuid()
            bind.execute(
                sa.text(
                    "INSERT INTO section_templates "
                    "(id, report_template_id, stable_key, title, process_module, display_order, required_on_final, owner_removable) "
                    "VALUES (:id, :template_id, 'printing', 'Printing', 'PRINTING', 220, :required, :removable)"
                ),
                {
                    "id": printing_template_id,
                    "template_id": template_id,
                    "required": False,
                    "removable": True,
                },
            )

        active_reports = bind.execute(
            sa.text(
                "SELECT id, owner_id FROM reports "
                "WHERE report_template_id = :template_id "
                "AND state NOT IN ('FINALIZED', 'DELETED')"
            ),
            {"template_id": template_id},
        ).all()

        for report_id, owner_id in active_reports:
            existing_section = bind.execute(
                sa.text(
                    "SELECT id FROM report_sections "
                    "WHERE report_id = :report_id AND stable_key = 'printing'"
                ),
                {"report_id": report_id},
            ).scalar_one_or_none()
            if existing_section:
                continue
            bind.execute(
                sa.text(
                    "UPDATE report_sections SET display_order = display_order + 10 "
                    "WHERE report_id = :report_id AND display_order >= 220"
                ),
                {"report_id": report_id},
            )
            bind.execute(
                sa.text(
                    "INSERT INTO report_sections "
                    "(id, report_id, section_template_id, stable_key, title, process_module, display_order, state, "
                    "required_on_final, removed_reason, narrative, version, created_by, updated_by, assigned_to_user_id, created_at, updated_at) "
                    "VALUES (:id, :report_id, :template_id, 'printing', 'Printing', 'PRINTING', 220, 'NOT_STARTED', "
                    ":required, NULL, '', 1, :owner_id, :owner_id, NULL, :created_at, :updated_at)"
                ),
                {
                    "id": _uuid(),
                    "report_id": report_id,
                    "template_id": printing_template_id,
                    "required": False,
                    "owner_id": owner_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    for order, stable_key, question, answer_type, priority, required in PROCESS_PROMPTS:
        exists = bind.execute(
            sa.text(
                "SELECT id FROM prompt_definitions "
                "WHERE process_module = 'PRINTING' AND stable_key = :stable_key AND version = 1"
            ),
            {"stable_key": stable_key},
        ).scalar_one_or_none()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO prompt_definitions "
                "(id, process_module, stable_key, question, answer_type, display_order, mobile_priority, required_on_final, active, version, output_path) "
                "VALUES (:id, 'PRINTING', :stable_key, :question, :answer_type, :display_order, :mobile_priority, :required, :active, 1, NULL)"
            ),
            {
                "id": _uuid(),
                "stable_key": stable_key,
                "question": question,
                "answer_type": answer_type,
                "display_order": order,
                "mobile_priority": priority,
                "required": required,
                "active": True,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM report_sections WHERE stable_key = 'printing' AND process_module = 'PRINTING'"))
    bind.execute(sa.text("UPDATE report_sections SET display_order = display_order - 10 WHERE display_order >= 230"))
    bind.execute(sa.text("DELETE FROM section_templates WHERE stable_key = 'printing' AND process_module = 'PRINTING'"))
    bind.execute(sa.text("UPDATE section_templates SET display_order = display_order - 10 WHERE display_order >= 230"))
    bind.execute(sa.text("DELETE FROM prompt_definitions WHERE process_module = 'PRINTING' AND version = 1"))
