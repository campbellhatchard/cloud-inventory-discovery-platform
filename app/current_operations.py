from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CapabilityMapping, Finding, ReportSection

CURRENT_OPERATION_TYPES = (
    "OBSERVATION",
    "PAIN_POINT",
    "RISK",
    "GAP",
    "STRENGTH",
    "OPPORTUNITY",
)
CURRENT_FINDING_EXCLUDED_STATUSES = ("REJECTED", "SUPERSEDED")
NARRATIVE_DERIVED_SOURCE = "NARRATIVE_DERIVED"

_LABELS = {
    "OBSERVATION": "Observation",
    "PAIN_POINT": "Pain Point",
    "RISK": "Risk",
    "GAP": "Gap",
    "STRENGTH": "Strength",
    "OPPORTUNITY": "Opportunity",
}
_HEADING_RE = re.compile(
    r"^\s*(Observation|Pain[ _-]?Point|Risk|Gap|Strength|Opportunity)\s*:\s*$",
    re.IGNORECASE,
)
_IMPACT_RE = re.compile(r"^\s*Impact\s*:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class NarrativeEntry:
    finding_type: str
    statement: str
    impact: str | None = None

    @property
    def label(self) -> str:
        return _LABELS[self.finding_type]


def normalize_finding_type(value: str | None) -> str:
    normalized = re.sub(r"[\s-]+", "_", (value or "OBSERVATION").strip().upper())
    if normalized not in CURRENT_OPERATION_TYPES:
        raise ValueError(f"Unsupported current-operations type: {value}")
    return normalized


def narrative_heading(finding_type: str) -> str:
    return f"{_LABELS[normalize_finding_type(finding_type)]}:"


def append_narrative_entry(
    narrative: str,
    *,
    finding_type: str,
    statement: str,
    impact: str | None = None,
) -> str:
    note = statement.strip()
    if not note:
        return narrative.strip()
    lines = [narrative_heading(finding_type), note]
    if impact and impact.strip():
        lines.append(f"Impact: {impact.strip()}")
    block = "\n".join(lines)
    current = narrative.strip()
    return f"{current}\n\n{block}" if current else block


def _heading_type(line: str) -> str | None:
    match = _HEADING_RE.match(line)
    if not match:
        return None
    return normalize_finding_type(match.group(1))


def _entry_from_lines(finding_type: str, lines: list[str]) -> NarrativeEntry | None:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return None

    impact: str | None = None
    impact_match = _IMPACT_RE.match(lines[-1])
    if impact_match:
        impact = impact_match.group(1).strip() or None
        lines = lines[:-1]
        while lines and not lines[-1].strip():
            lines.pop()
    statement = "\n".join(lines).strip()
    if not statement:
        return None
    return NarrativeEntry(normalize_finding_type(finding_type), statement, impact)


def parse_current_operations_narrative(narrative: str | None) -> list[NarrativeEntry]:
    text = (narrative or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []

    entries: list[NarrativeEntry] = []
    current_type = "OBSERVATION"
    current_lines: list[str] = []
    saw_heading = False

    def flush() -> None:
        nonlocal current_lines
        entry = _entry_from_lines(current_type, current_lines)
        if entry:
            entries.append(entry)
        current_lines = []

    for line in text.split("\n"):
        heading_type = _heading_type(line)
        if heading_type:
            flush()
            current_type = heading_type
            saw_heading = True
            continue
        current_lines.append(line)
    flush()

    if not saw_heading and entries:
        # A free-form legacy narrative remains a single Observation.
        return [NarrativeEntry("OBSERVATION", text.strip(), None)]
    return entries


def _entry_key(finding_type: str, statement: str, impact: str | None) -> tuple[str, str, str]:
    return (
        normalize_finding_type(finding_type),
        statement.strip(),
        (impact or "").strip(),
    )


def sync_narrative_findings(
    db: Session,
    *,
    report_id: str,
    section: ReportSection,
    actor_user_id: str,
) -> list[Finding]:
    """Synchronize the internal typed-finding index from the canonical narrative.

    The report section narrative is the user-facing source of truth. Finding rows
    generated here exist only to preserve typed downstream behavior such as
    readiness checks, AI grounding, mappings, and benefits. They are never a
    separate user-editing surface.
    """
    parsed = parse_current_operations_narrative(section.narrative)
    existing = list(
        db.scalars(
            select(Finding)
            .where(
                Finding.report_id == report_id,
                Finding.section_id == section.id,
                Finding.source_type == NARRATIVE_DERIVED_SOURCE,
                Finding.status.notin_(CURRENT_FINDING_EXCLUDED_STATUSES),
            )
            .order_by(Finding.created_at, Finding.id)
        ).all()
    )

    buckets: dict[tuple[str, str, str], deque[Finding]] = defaultdict(deque)
    for item in existing:
        buckets[_entry_key(item.finding_type, item.statement, item.impact)].append(item)

    current: list[Finding] = []
    retained_ids: set[str] = set()
    for entry in parsed:
        key = _entry_key(entry.finding_type, entry.statement, entry.impact)
        item = buckets[key].popleft() if buckets[key] else None
        if item is None:
            item = Finding(
                report_id=report_id,
                section_id=section.id,
                finding_type=entry.finding_type,
                statement=entry.statement,
                impact=entry.impact,
                confidence="MEDIUM",
                status="DRAFT",
                source_type=NARRATIVE_DERIVED_SOURCE,
                created_by=actor_user_id,
            )
            db.add(item)
            db.flush()
        retained_ids.add(item.id)
        current.append(item)

    for item in existing:
        if item.id not in retained_ids:
            item.status = "SUPERSEDED"
            for mapping in db.scalars(
                select(CapabilityMapping).where(
                    CapabilityMapping.finding_id == item.id,
                    CapabilityMapping.approval_state.in_(("PENDING", "APPROVED")),
                )
            ).all():
                mapping.approval_state = "STALE"

    return current


def current_findings(items: Iterable[Finding]) -> list[Finding]:
    return [item for item in items if item.status not in CURRENT_FINDING_EXCLUDED_STATUSES]
