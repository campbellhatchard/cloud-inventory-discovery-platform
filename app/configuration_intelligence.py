from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any


CONFIGURATION_SOURCE_TYPE = "CONTROLLED_CONFIGURATION_REFERENCE"
CONFIGURATION_KNOWLEDGE_KIND = "PRODUCT_CONFIGURATION"

# High-level capability mapping only. Detailed settings remain knowledge and are
# deliberately not promoted into the capability catalog.
QUESTION_CAPABILITY_OVERRIDES: dict[str, str | None] = {
    # Platform / organizational structure
    "gs-base-004": "CAP-ORG-001",
    "gs-co-001": "CAP-ORG-001", "gs-co-002": "CAP-ORG-001", "gs-co-003": "CAP-ORG-001", "gs-co-004": "CAP-ORG-001",
    "gs-wh-001": "CAP-ORG-001", "gs-wh-002": "CAP-ORG-001", "gs-wh-003": "CAP-ORG-001",
    "gs-wh-004": "CAP-INT-001", "gs-wh-005": "CAP-INT-001", "gs-org-002": "CAP-ORG-001", "gs-org-003": "CAP-ORG-001",
    # Integration
    "gs-int-001": "CAP-INT-001", "gs-int-002": "CAP-INT-001", "gs-int-003": "CAP-INT-001", "gs-int-004": "CAP-INT-001",
    # Locations / zones
    "gs-loc-001": "CAP-LOC-001", "gs-loc-002": "CAP-LOC-001", "gs-loc-003": "CAP-LOC-001", "gs-loc-004": "CAP-LOC-001",
    "gs-loc-005": "CAP-LOC-001", "gs-loc-006": "CAP-LOC-001", "gs-loc-007": "CAP-LOC-001", "gs-loc-008": "CAP-LOC-001",
    "gs-loc-009": "CAP-LOC-001", "gs-loc-010": "CAP-LOC-001",
    # Holds
    "gs-avail-001": "CAP-AVL-001", "gs-avail-002": "CAP-AVL-001", "gs-avail-003": "CAP-AVL-001", "gs-avail-004": "CAP-AVL-001", "gs-avail-005": "CAP-AVL-001",
    # Inbound
    "gs-inb-001": "CAP-INB-001", "gs-inb-009": "CAP-INB-001", "gs-inb-002": "CAP-INB-001", "gs-inb-003": "CAP-INB-001",
    "gs-inb-004": "CAP-IHU-001", "gs-inb-018": "CAP-IHU-001", "gs-inb-005": "CAP-INB-001", "gs-inb-006": "CAP-INB-001",
    "gs-inb-010": "CAP-BCS-001", "gs-inb-011": "CAP-BCS-001", "gs-inb-012": "CAP-BCS-001", "gs-inb-013": "CAP-INB-001",
    "gs-inb-015": "CAP-LOT-001", "gs-inb-016": "CAP-LOT-001", "gs-inb-017": "CAP-INV-001",
    "gs-inb-007": "CAP-INB-002", "gs-inb-008": "CAP-INB-002", "gs-inb-014": "CAP-INB-002",
    # Putaway
    "gs-put-001": "CAP-PUT-001", "gs-put-002": "CAP-PUT-001", "gs-put-003": "CAP-PUT-001", "gs-put-004": "CAP-PUT-001", "gs-put-005": "CAP-PUT-001", "gs-put-006": "CAP-PUT-001",
    # Inventory control
    "gs-invc-001": "CAP-LOT-001", "gs-invc-002": "CAP-LOT-001", "gs-invc-003": "CAP-LOT-001", "gs-invc-004": "CAP-LOT-001",
    "gs-invc-005": "CAP-IHU-001", "gs-invc-006": "CAP-IHU-001",
    "gs-invc-007": "CAP-INV-001", "gs-invc-008": "CAP-INV-001", "gs-invc-009": "CAP-INV-001", "gs-invc-010": "CAP-TRN-001",
    "gs-invc-011": "CAP-INV-001", "gs-invc-012": "CAP-LOC-001", "gs-invc-013": "CAP-INV-001", "gs-invc-014": "CAP-FLD-001", "gs-invc-015": "CAP-REQ-001",
    # Count
    "gs-cc-001": "CAP-CC-001", "gs-cc-002": "CAP-CC-001", "gs-cc-003": "CAP-CC-001", "gs-cc-004": "CAP-CC-001", "gs-cc-005": "CAP-CC-001", "gs-cc-006": "CAP-CC-002",
    # Outbound
    "gs-out-001": "CAP-ALL-001", "gs-out-002": "CAP-PCK-002", "gs-out-003": "CAP-ALL-001", "gs-out-004": "CAP-SHP-001", "gs-out-005": "CAP-SHP-001",
    "gs-out-006": "CAP-SHP-001", "gs-out-007": "CAP-ALL-001", "gs-out-008": "CAP-ALL-001", "gs-out-009": "CAP-PCK-002",
    "gs-out-010": "CAP-SHP-002", "gs-out-011": "CAP-SHP-002", "gs-out-012": "CAP-SHP-001",
    # Returns
    "gs-ret-001": "CAP-INB-003", "gs-ret-002": "CAP-INB-003", "gs-ret-003": "CAP-INB-003", "gs-ret-004": "CAP-INB-003",
    # Picking / waves / kits
    "gs-pf-001": "CAP-PCK-001", "gs-pf-002": "CAP-PCK-001", "gs-pf-003": "CAP-PCK-001", "gs-pf-004": "CAP-PCK-001",
    "gs-pf-005": "CAP-WAV-001", "gs-pf-006": "CAP-PCK-001", "gs-pf-007": "CAP-PCK-001", "gs-pf-008": "CAP-KIT-001", "gs-pf-009": "CAP-KIT-001", "gs-pf-010": "CAP-WAV-001",
    # Replenishment
    "gs-rep-001": "CAP-RPL-001", "gs-rep-002": "CAP-RPL-001", "gs-rep-003": "CAP-RPL-001", "gs-rep-004": "CAP-RPL-001",
    # Barcode / guided transaction defaults
    "gs-bc-001": "CAP-BCS-001", "gs-bc-002": "CAP-BCS-001",
    "gs-cf-001": "CAP-MOB-001", "gs-cf-002": "CAP-MOB-001", "gs-cf-003": "CAP-MOB-001", "gs-cf-004": "CAP-MOB-001", "gs-cf-005": "CAP-MOB-001",
    # Non-standard / advanced. Cross-dock is intentionally not mapped to a
    # supported capability: the source labels it non-standard.
    "gs-ns-001": "CAP-INT-001", "gs-ns-002": "CAP-INT-001", "gs-ns-003": None, "gs-ns-004": "CAP-INT-001", "gs-ns-005": "CAP-RPT-001",
}

SECTION_MODULES: dict[str, str] = {
    "Tenant & Environment Setup": "Administration",
    "Base Module & Solution": "Administration",
    "Company Structure": "Cross-process",
    "Warehouses": "Cross-process",
    "ERP Integration": "Integration",
    "Locations & Zones": "Cross-process",
    "Availability Status & Holds": "Inventory Control",
    "Inbound & Receiving": "Receiving",
    "Putaway": "Putaway",
    "Inventory Control": "Inventory Control",
    "Cycle Counting": "Cycle Count",
    "Outbound, Picking & Shipping": "Order Management / Picking / Shipping",
    "Returns": "Receiving / Outbound",
    "Guided Pick Flows": "Picking",
    "Replenishment & Fixed Picking": "Replenishment",
    "Barcodes & Scanning": "Cross-process",
    "Transaction Confirmation Defaults": "Cross-process",
    "Non-Standard / Advanced": "Integration / Cross-process",
}

TOPIC_OVERRIDES: dict[str, str] = {
    "gs-loc-001": "Inventory location identification and numbering",
    "gs-loc-002": "Operational location types",
    "gs-loc-003": "Warehouse zones",
    "gs-loc-004": "Zone types and warehouse assignment",
    "gs-loc-005": "Location mixing restrictions",
    "gs-loc-006": "Inventory mixing rules",
    "gs-loc-007": "Location capacity during putaway",
    "gs-loc-008": "Storage location and specialist storage types",
    "gs-loc-009": "Multi-item location storage",
    "gs-loc-010": "Location groups for putaway direction",
    "gs-bc-001": "Mobile barcode scanning",
    "gs-bc-002": "Barcode formats and encoded data",
    "gs-ns-003": "Cross-dock scope signal",
}


@dataclass(frozen=True)
class ConfigurationRecord:
    source_ref: str
    source_version: str
    title: str
    process_module: str | None
    content: str
    capability_code: str | None
    structured_data: dict[str, Any]


def _version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return (0,)
    nums = re.findall(r"\d+", value)
    return tuple(int(part) for part in nums) or (0,)


def load_configuration_template(data: bytes, filename: str) -> dict[str, Any]:
    """Load a Guided Setup template from JSON or a ZIP containing JSON.

    For ZIPs, the highest semantic template version with a sections array is
    selected. HTML/JS artifacts are never interpreted as product knowledge.
    """
    lower = filename.lower()
    candidates: list[dict[str, Any]] = []
    if lower.endswith(".json"):
        candidates.append(json.loads(data.decode("utf-8-sig")))
    elif lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total_uncompressed = sum(item.file_size for item in archive.infolist())
            if total_uncompressed > 25_000_000:
                raise ValueError("Configuration ZIP expands beyond the safe import limit.")
            for item in archive.infolist():
                if item.is_dir() or not item.filename.lower().endswith(".json"):
                    continue
                if item.file_size > 5_000_000:
                    continue
                try:
                    candidate = json.loads(archive.read(item).decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(candidate, dict) and isinstance(candidate.get("sections"), list):
                    candidates.append(candidate)
    else:
        raise ValueError("Configuration knowledge import supports JSON or ZIP files.")

    candidates = [item for item in candidates if isinstance(item, dict) and isinstance(item.get("sections"), list)]
    if not candidates:
        raise ValueError("No Guided Setup interview template was found in the supplied file.")
    candidates.sort(key=lambda item: _version_key(str((item.get("_meta") or {}).get("version") or "0")), reverse=True)
    return candidates[0]


def _strip_question(text: str) -> str:
    value = re.sub(r"^\([^)]*\)\s*-\s*", "", (text or "").strip())
    return value.rstrip(" ?")


def _extract_system_references(source: str) -> list[str]:
    refs = set(re.findall(r"\bnsC7[A-Za-z0-9_]*\b", source or ""))
    return sorted(refs)


def _claim_strength(question: dict[str, Any]) -> str:
    source = str(question.get("source") or "")
    guidance = str(question.get("guidance") or "")
    if "Not Standard Functionality" in source or question.get("id") == "gs-ns-003":
        return "SCOPE_SIGNAL_ONLY"
    if "System object" in source or "System objects" in source or "Release Notes connector" in source or "Platform help" in guidance:
        return "PRODUCT_DEFINED"
    return "GUIDED_SETUP_DEFINED"


def _knowledge_role(question: dict[str, Any], section_title: str) -> str:
    qid = str(question.get("id") or "")
    if qid.startswith("gs-ten-") or qid in {"gs-base-001", "gs-base-002", "gs-base-003"}:
        return "PLATFORM_SETUP"
    if qid == "gs-ns-003":
        return "NON_STANDARD_SIGNAL"
    if section_title in {"Company Structure", "Warehouses", "ERP Integration"}:
        return "SOLUTION_PREREQUISITE"
    return "CAPABILITY_CONFIGURATION"


def _content_for(question: dict[str, Any], section_title: str) -> str:
    qid = str(question.get("id") or "")
    topic = TOPIC_OVERRIDES.get(qid) or _strip_question(str(question.get("text") or ""))
    guidance = str(question.get("guidance") or "").strip()
    options = [str(item).strip() for item in question.get("options") or [] if str(item).strip()]

    if qid == "gs-ns-003":
        return (
            "The Guided Setup source flags cross-dock operations as non-standard. "
            "Treat cross-dock observations as a specialist/scope-validation signal; this record does not establish standard Cloud Inventory support."
        )

    parts = [f"Configuration topic: {topic}."]
    if guidance:
        # Preserve source terminology while preventing implementation instructions
        # from masquerading as the high-level capability description.
        parts.append(f"Defined behavior/guidance: {guidance}")
    if options:
        label = "Defined configuration values" if len(options) > 1 else "Defined configuration value"
        parts.append(f"{label}: {', '.join(options)}.")
    if question.get("multiSelect"):
        parts.append("The source permits multiple selections for this configuration topic.")
    return " ".join(parts)


def normalize_configuration_template(
    template: dict[str, Any],
    *,
    source_name: str,
    corroborating_sources: list[dict[str, str]] | None = None,
) -> list[ConfigurationRecord]:
    meta = template.get("_meta") or {}
    version = str(meta.get("version") or "unknown")
    records: list[ConfigurationRecord] = []
    seen: set[str] = set()

    for section in template.get("sections") or []:
        section_title = str(section.get("title") or section.get("id") or "Configuration").strip()
        process_module = SECTION_MODULES.get(section_title, section_title[:100] or None)
        for question in section.get("questions") or []:
            qid = str(question.get("id") or "").strip()
            if not qid or qid in seen:
                continue
            seen.add(qid)
            topic = TOPIC_OVERRIDES.get(qid) or _strip_question(str(question.get("text") or qid))
            source = str(question.get("source") or "").strip()
            source_refs = [{"name": source_name, "version": version, "question_id": qid, "source": source}]
            for item in corroborating_sources or []:
                source_refs.append({**item, "question_id": qid})
            structured = {
                "canonical_key": qid,
                "source_question_id": qid,
                "source_question": str(question.get("text") or "").strip(),
                "guidance": str(question.get("guidance") or "").strip(),
                "options": [str(item) for item in question.get("options") or []],
                "answer_type": str(question.get("type") or "text"),
                "multi_select": bool(question.get("multiSelect")),
                "branches": question.get("branches") or [],
                "default_next": question.get("default_next"),
                "optional": bool(question.get("optional")),
                "example": str(question.get("example") or "").strip() or None,
                "source_citation": source or None,
                "source_references": source_refs,
                "system_references": _extract_system_references(f"{source} {question.get('guidance') or ''}"),
                "knowledge_role": _knowledge_role(question, section_title),
                "claim_strength": _claim_strength(question),
                "customer_facing_capability_detail": False,
                "never_use_as_discovery_prompt": True,
            }
            records.append(ConfigurationRecord(
                source_ref=f"configuration:guided-setup:{qid}",
                source_version=version,
                title=topic[:250],
                process_module=process_module,
                content=_content_for(question, section_title),
                capability_code=QUESTION_CAPABILITY_OVERRIDES.get(qid),
                structured_data=structured,
            ))
    return records


def solution_relevant(record: dict[str, Any]) -> bool:
    structured = record.get("structured_data") or {}
    return structured.get("knowledge_role") not in {"PLATFORM_SETUP"}
