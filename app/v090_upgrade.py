from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from .models import ReportSection, SectionTemplate


def apply_v090_data_upgrade(db: Session) -> None:
    """Apply the idempotent v0.9.0 navigation/data-label upgrade.

    Existing "General Operational Observations" content is preserved in place.
    Only the user-facing title and display order change so Quick Entry "Other"
    maps to a real report page beneath Manufacturing.
    """
    db.execute(
        update(SectionTemplate)
        .where(SectionTemplate.stable_key == "general-observations")
        .values(title="Other", display_order=255)
    )
    db.execute(
        update(ReportSection)
        .where(ReportSection.stable_key == "general-observations")
        .values(title="Other", display_order=255)
    )
    db.commit()
