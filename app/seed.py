from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select

from .auth import hash_password
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import (
    BrandingProfile,
    Capability,
    KnowledgeEntry,
    PromptDefinition,
    ReportTemplate,
    SectionTemplate,
    User,
    UserRole,
)

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIDENTIALITY = (
    "This document is the property of and proprietary to Cloud Inventory and contains trade secret and confidential information, "
    "and is solely for the Customer's internal use. Without the express written consent of Cloud Inventory, this document shall not "
    "be used, reproduced, copied, disclosed, or transmitted, in whole or in part. Copyright Cloud Inventory. All rights reserved."
)

SECTIONS = [
    (10, "opportunity", "Opportunity Overview", None, True, False),
    (20, "company-profile", "Company and Site Profile", None, True, False),
    (30, "products-handled", "Products and Materials Handled", None, True, True),
    (40, "operational-footprint", "Operational Footprint and Distribution Network", None, False, True),
    (50, "master-data", "Master Data", None, True, True),
    (60, "systems-landscape", "IT and Systems Landscape", None, True, True),
    (70, "survey-background", "Survey Background and Attendees", None, True, True),
    (80, "survey-objectives", "Site Survey Objectives", None, True, True),
    (90, "executive-summary", "Executive Summary", None, True, True),
    (100, "vision-pain-points", "Vision, Pain Points, and Desired Outcomes", None, True, True),
    (110, "solution-viability", "Cloud Inventory Solution Viability", None, True, True),
    (120, "general-observations", "General Operational Observations", None, True, True),
    (130, "receiving", "Receiving", "RECEIVING", False, True),
    (140, "putaway", "Putaway", "PUTAWAY", False, True),
    (150, "transfer", "Transfer", "TRANSFER", False, True),
    (160, "order-management", "Order Management", "ORDER_MANAGEMENT", False, True),
    (170, "picking", "Picking", "PICKING", False, True),
    (180, "packing", "Packing", "PACKING", False, True),
    (190, "shipping", "Shipping", "SHIPPING", False, True),
    (200, "cycle-count", "Cycle Count Management", "CYCLE_COUNT", False, True),
    (210, "work-orders", "Work Orders", "WORK_ORDERS", False, True),
    (220, "printing", "Printing", "PRINTING", False, True),
    (230, "field-inventory", "Field Inventory", "FIELD_INVENTORY", False, True),
    (240, "manufacturing", "Manufacturing", "MANUFACTURING", False, True),
    (250, "cross-process", "Cross-Process Findings and Dependencies", None, False, True),
    (260, "recommended-capabilities", "Recommended Cloud Inventory Capabilities", None, False, True),
    (270, "expected-benefits", "Expected Benefits", None, False, True),
    (280, "risks-assumptions", "Risks, Assumptions, and Prerequisites", None, False, True),
    (290, "next-steps", "Recommended Next Steps", None, False, True),
    (300, "supporting-evidence", "Supporting Evidence and Attachments", None, False, True),
]

GENERAL_PROMPTS = [
    (10, "purpose", "What is the purpose and intended outcome of this section?", "LONG_TEXT", "HIGH", True),
    (20, "facts", "What facts were directly observed or confirmed by the prospect?", "LONG_TEXT", "HIGH", True),
    (30, "assumptions", "What assumptions remain unverified?", "LONG_TEXT", "NORMAL", False),
    (40, "open-questions", "What open questions require customer follow-up?", "LONG_TEXT", "NORMAL", False),
]

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


def seed() -> None:
    settings = get_settings()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
        if not admin:
            password = settings.bootstrap_admin_password
            if not password:
                if settings.environment == "production":
                    raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD is required in production.")
                password = "ChangeMe-Development-Only!"
                print("WARNING: development bootstrap admin password is ChangeMe-Development-Only!")
            admin = User(username=settings.bootstrap_admin_username, email=settings.bootstrap_admin_email, display_name="Administrator", password_hash=hash_password(password), force_password_change=True)
            db.add(admin)
            db.flush()
            db.add(UserRole(user_id=admin.id, role="ADMIN"))
            db.add(UserRole(user_id=admin.id, role="OWNER"))

        brand = db.scalar(select(BrandingProfile).where(BrandingProfile.name == "Denver Cloud Inventory", BrandingProfile.version == 1))
        if not brand:
            brand = BrandingProfile(name="Denver Cloud Inventory", version=1, is_default=True, primary_color="#1F3447", secondary_color="#00A7C7", accent_color="#6B7785", heading_font="Aptos Display", body_font="Aptos", confidentiality_text=DEFAULT_CONFIDENTIALITY, draft_watermark="DRAFT - CONFIDENTIAL", footer_text="Cloud Inventory | Confidential", created_by=admin.id)
            db.add(brand)
            db.flush()

        template = db.scalar(select(ReportTemplate).where(ReportTemplate.name == "Cloud Inventory Full Site Discovery", ReportTemplate.version == 1))
        if not template:
            template = ReportTemplate(name="Cloud Inventory Full Site Discovery", report_type="FULL_DISCOVERY", version=1, status="ACTIVE", branding_profile_id=brand.id)
            db.add(template)
            db.flush()
            for order, stable, title, module, required, removable in SECTIONS:
                db.add(SectionTemplate(report_template_id=template.id, stable_key=stable, title=title, process_module=module, display_order=order, required_on_final=required, owner_removable=removable))

        for order, stable, question, answer_type, priority, required in GENERAL_PROMPTS:
            if not db.scalar(select(PromptDefinition).where(PromptDefinition.process_module.is_(None), PromptDefinition.stable_key == stable, PromptDefinition.version == 1)):
                db.add(PromptDefinition(process_module=None, stable_key=stable, question=question, answer_type=answer_type, display_order=order, mobile_priority=priority, required_on_final=required, version=1))
        for module in ["RECEIVING", "PUTAWAY", "TRANSFER", "ORDER_MANAGEMENT", "PICKING", "PACKING", "SHIPPING", "CYCLE_COUNT", "WORK_ORDERS", "PRINTING", "FIELD_INVENTORY", "MANUFACTURING"]:
            for order, stable, question, answer_type, priority, required in PROCESS_PROMPTS:
                if not db.scalar(select(PromptDefinition).where(PromptDefinition.process_module == module, PromptDefinition.stable_key == stable, PromptDefinition.version == 1)):
                    db.add(PromptDefinition(process_module=module, stable_key=stable, question=question, answer_type=answer_type, display_order=order, mobile_priority=priority, required_on_final=required, version=1))

        cap_path = ROOT / "assets" / "capability-seed.csv"
        if cap_path.exists():
            with cap_path.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    code = (row.get("capability_code") or row.get("capability_id") or "").strip()
                    if not code or db.scalar(select(Capability).where(Capability.capability_code == code)):
                        continue
                    db.add(Capability(
                        capability_code=code,
                        name=(row.get("name") or code).strip(),
                        domain=(row.get("domain") or "General").strip(),
                        controlled_description=(row.get("controlled_description") or "").strip(),
                        typical_prerequisites=(row.get("typical_prerequisites") or "").strip() or None,
                        limitations=(row.get("limitations") or "").strip() or None,
                        status="APPROVED" if "approved" in (row.get("status") or "").lower() and "requires" not in (row.get("status") or "").lower() else "PROPOSED",
                        source=(row.get("source") or "Advanced Inventory and approved discovery-report corpus").strip(),
                    ))
        db.flush()
        for capability in db.scalars(select(Capability).order_by(Capability.capability_code)).all():
            source_ref = f"capability:{capability.capability_code}"
            if db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.source_ref == source_ref)):
                continue
            content = capability.controlled_description
            if capability.typical_prerequisites:
                content += f"\nPrerequisites: {capability.typical_prerequisites}"
            if capability.limitations:
                content += f"\nLimitations: {capability.limitations}"
            db.add(KnowledgeEntry(
                source_type="CONTROLLED_PRODUCT_REFERENCE",
                source_ref=source_ref,
                title=f"{capability.name} ({capability.capability_code})",
                process_module=capability.domain,
                content=content,
                capability_id=capability.id,
                prospect_id=None,
                classification="INTERNAL",
                reusable_across_prospects=True,
                approval_state="APPROVED" if capability.status == "APPROVED" else "PENDING",
                approved_by=admin.id if capability.status == "APPROVED" else None,
                created_by=admin.id,
            ))
        db.commit()
        print("Seed complete.")


if __name__ == "__main__":
    seed()
