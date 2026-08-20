"""User administration hardening and photograph AI retirement.

Revision ID: k61h4c0f8d21
Revises: j50g3b9e7c10
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "k61h4c0f8d21"
down_revision = "j50g3b9e7c10"
branch_labels = None
depends_on = None

PHOTO_PURPOSES = ("PHOTO_ANALYSIS", "PHOTO_CONTEXT_REVISION")
RETIREMENT_MESSAGE = "Photograph AI processing was retired in application version 0.8.6."


def upgrade() -> None:
    bind = op.get_bind()

    ai_jobs = sa.table(
        "ai_jobs",
        sa.column("id", sa.String()),
        sa.column("purpose", sa.String()),
        sa.column("status", sa.String()),
        sa.column("error", sa.Text()),
        sa.column("completed_at", sa.DateTime(timezone=True)),
    )
    ai_suggestions = sa.table(
        "ai_suggestions",
        sa.column("id", sa.String()),
        sa.column("purpose", sa.String()),
        sa.column("review_state", sa.String()),
    )
    jobs = sa.table(
        "jobs",
        sa.column("id", sa.String()),
        sa.column("job_type", sa.String()),
        sa.column("payload", sa.JSON()),
        sa.column("status", sa.String()),
        sa.column("error", sa.Text()),
        sa.column("completed_at", sa.DateTime(timezone=True)),
    )

    photo_ai_job_ids = [
        row.id
        for row in bind.execute(
            sa.select(ai_jobs.c.id).where(ai_jobs.c.purpose.in_(PHOTO_PURPOSES))
        )
    ]

    bind.execute(
        sa.update(ai_jobs)
        .where(ai_jobs.c.purpose.in_(PHOTO_PURPOSES))
        .where(ai_jobs.c.status.not_in(("COMPLETED", "FAILED", "BLOCKED")))
        .values(status="BLOCKED", error=RETIREMENT_MESSAGE, completed_at=sa.func.now())
    )
    bind.execute(
        sa.update(ai_suggestions)
        .where(ai_suggestions.c.purpose.in_(PHOTO_PURPOSES))
        .where(ai_suggestions.c.review_state != "APPROVED")
        .values(review_state="SUPERSEDED")
    )

    if photo_ai_job_ids:
        for row in bind.execute(
            sa.select(jobs.c.id, jobs.c.payload, jobs.c.status)
            .where(jobs.c.job_type == "ai.generate")
        ):
            payload = row.payload if isinstance(row.payload, dict) else {}
            if payload.get("ai_job_id") in photo_ai_job_ids and row.status not in {"COMPLETED", "FAILED"}:
                bind.execute(
                    sa.update(jobs)
                    .where(jobs.c.id == row.id)
                    .values(status="FAILED", error=RETIREMENT_MESSAGE, completed_at=sa.func.now())
                )

    op.drop_index("ix_evidence_ai_observations_section_id", table_name="evidence_ai_observations")
    op.drop_index("ix_evidence_ai_observations_report_id", table_name="evidence_ai_observations")
    op.drop_index("ix_evidence_ai_observations_evidence_id", table_name="evidence_ai_observations")
    op.drop_table("evidence_ai_observations")


def downgrade() -> None:
    # Historical photograph-AI rows are intentionally not reconstructed. The
    # legacy table is recreated empty only to restore the prior schema shape.
    op.create_table(
        "evidence_ai_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("source_file_sha256", sa.String(length=64), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["report_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id"),
    )
    op.create_index("ix_evidence_ai_observations_evidence_id", "evidence_ai_observations", ["evidence_id"], unique=False)
    op.create_index("ix_evidence_ai_observations_report_id", "evidence_ai_observations", ["report_id"], unique=False)
    op.create_index("ix_evidence_ai_observations_section_id", "evidence_ai_observations", ["section_id"], unique=False)
