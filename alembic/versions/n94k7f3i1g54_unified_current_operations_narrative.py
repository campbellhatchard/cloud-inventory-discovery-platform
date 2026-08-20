"""Unified Current Operations Narrative

Revision ID: n94k7f3i1g54
Revises: m83j6e2h0f43
Create Date: 2026-08-06
"""
from __future__ import annotations

from collections import defaultdict

from alembic import op
import sqlalchemy as sa

revision = "n94k7f3i1g54"
down_revision = "m83j6e2h0f43"
branch_labels = None
depends_on = None

_LABELS = {
    "OBSERVATION": "Observation",
    "PAIN_POINT": "Pain Point",
    "RISK": "Risk",
    "GAP": "Gap",
    "STRENGTH": "Strength",
    "OPPORTUNITY": "Opportunity",
}


def _block(finding_type: str, statement: str, impact: str | None) -> str:
    label = _LABELS.get((finding_type or "OBSERVATION").upper(), "Observation")
    lines = [f"{label}:", (statement or "").strip()]
    if impact and impact.strip():
        lines.append(f"Impact: {impact.strip()}")
    return "\n".join(line for line in lines if line)


def upgrade() -> None:
    with op.batch_alter_table("findings") as batch:
        batch.add_column(
            sa.Column(
                "source_type",
                sa.String(length=30),
                nullable=False,
                server_default="LEGACY",
            )
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT f.id, f.section_id, f.finding_type, f.statement, f.impact,
                   rs.narrative
            FROM findings f
            JOIN report_sections rs ON rs.id = f.section_id
            WHERE f.status <> 'REJECTED'
            ORDER BY f.section_id, f.created_at, f.id
            """
        )
    ).mappings().all()

    by_section: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_section[str(row["section_id"])].append(dict(row))

    for section_id, findings in by_section.items():
        narrative = str(findings[0].get("narrative") or "").strip()
        for finding in findings:
            block = _block(
                str(finding.get("finding_type") or "OBSERVATION"),
                str(finding.get("statement") or ""),
                str(finding.get("impact") or "") or None,
            )
            if block and block not in narrative:
                narrative = f"{narrative}\n\n{block}" if narrative else block
        connection.execute(
            sa.text("UPDATE report_sections SET narrative = :narrative WHERE id = :section_id"),
            {"narrative": narrative, "section_id": section_id},
        )

    if rows:
        ids = [str(row["id"]) for row in rows]
        connection.execute(
            sa.text("UPDATE findings SET source_type = 'NARRATIVE_DERIVED' WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        )


def downgrade() -> None:
    # Narrative content is intentionally retained because it is the canonical
    # user-authored representation after this release. A downgrade removes only
    # the derived-index marker and does not discard user-visible text.
    with op.batch_alter_table("findings") as batch:
        batch.drop_column("source_type")
