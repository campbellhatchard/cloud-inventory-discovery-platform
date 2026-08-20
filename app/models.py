from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def uuid4_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    username_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(30), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Prospect(Base, TimestampMixin):
    __tablename__ = "prospects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    name: Mapped[str] = mapped_column(String(200), index=True)
    industry: Mapped[str | None] = mapped_column(String(150))
    opportunity: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    retention_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    logo_storage_key: Mapped[str | None] = mapped_column(Text)
    archive_prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ProspectMembership(Base):
    __tablename__ = "prospect_memberships"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_scope: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Site(Base, TimestampMixin):
    __tablename__ = "sites"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Engagement(Base, TimestampMixin):
    __tablename__ = "engagements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    survey_date: Mapped[date | None] = mapped_column(Date)
    objectives: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")


class EngagementMember(Base):
    __tablename__ = "engagement_members"
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    function_name: Mapped[str | None] = mapped_column(String(150))
    role_scope: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrandingProfile(Base, TimestampMixin):
    __tablename__ = "branding_profiles"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_color: Mapped[str] = mapped_column(String(7), default="#22364A")
    secondary_color: Mapped[str] = mapped_column(String(7), default="#00A9CE")
    accent_color: Mapped[str] = mapped_column(String(7), default="#6B7785")
    heading_font: Mapped[str] = mapped_column(String(100), default="Aptos Display")
    body_font: Mapped[str] = mapped_column(String(100), default="Aptos")
    confidentiality_text: Mapped[str] = mapped_column(Text)
    draft_watermark: Mapped[str] = mapped_column(String(100), default="DRAFT - CONFIDENTIAL")
    footer_text: Mapped[str] = mapped_column(String(500), default="Cloud Inventory | Confidential")
    photo_size_uom: Mapped[str] = mapped_column(String(12), default="INCHES")
    landscape_photo_width: Mapped[float] = mapped_column(Float, default=6.5)
    landscape_photo_height: Mapped[float] = mapped_column(Float, default=4.25)
    portrait_photo_width: Mapped[float] = mapped_column(Float, default=4.25)
    portrait_photo_height: Mapped[float] = mapped_column(Float, default=6.5)
    logo_storage_key: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ReportTemplate(Base):
    __tablename__ = "report_templates"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    name: Mapped[str] = mapped_column(String(150))
    report_type: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    branding_profile_id: Mapped[str | None] = mapped_column(ForeignKey("branding_profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SectionTemplate(Base):
    __tablename__ = "section_templates"
    __table_args__ = (UniqueConstraint("report_template_id", "stable_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_template_id: Mapped[str] = mapped_column(ForeignKey("report_templates.id", ondelete="CASCADE"))
    stable_key: Mapped[str] = mapped_column(String(150))
    title: Mapped[str] = mapped_column(String(250))
    process_module: Mapped[str | None] = mapped_column(String(100))
    display_order: Mapped[int] = mapped_column(Integer)
    required_on_final: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_removable: Mapped[bool] = mapped_column(Boolean, default=True)


class PromptDefinition(Base):
    __tablename__ = "prompt_definitions"
    __table_args__ = (UniqueConstraint("process_module", "stable_key", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    process_module: Mapped[str | None] = mapped_column(String(100), index=True)
    stable_key: Mapped[str] = mapped_column(String(150))
    question: Mapped[str] = mapped_column(Text)
    answer_type: Mapped[str] = mapped_column(String(30), default="LONG_TEXT")
    display_order: Mapped[int] = mapped_column(Integer)
    mobile_priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    required_on_final: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    output_path: Mapped[str | None] = mapped_column(String(250))


class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    report_template_id: Mapped[str] = mapped_column(ForeignKey("report_templates.id"))
    branding_profile_id: Mapped[str | None] = mapped_column(ForeignKey("branding_profiles.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(250))
    report_kind: Mapped[str] = mapped_column(String(20), default="CAPTURE")
    state: Mapped[str] = mapped_column(String(30), default="DRAFT")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    merged_into_report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.id"))
    recovery_delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportContentVersion(Base):
    __tablename__ = "report_content_versions"
    __table_args__ = (UniqueConstraint("report_id", "content_type", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    content_type: Mapped[str] = mapped_column(String(50), default="EXECUTIVE_SUMMARY")
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(30), default="USER")
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ai_suggestion_id: Mapped[str | None] = mapped_column(ForeignKey("ai_suggestions.id", ondelete="SET NULL"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportMember(Base):
    __tablename__ = "report_members"
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_scope: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportSection(Base, TimestampMixin):
    __tablename__ = "report_sections"
    __table_args__ = (UniqueConstraint("report_id", "stable_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_template_id: Mapped[str | None] = mapped_column(ForeignKey("section_templates.id"))
    stable_key: Mapped[str] = mapped_column(String(150))
    title: Mapped[str] = mapped_column(String(250))
    process_module: Mapped[str | None] = mapped_column(String(100), index=True)
    display_order: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    required_on_final: Mapped[bool] = mapped_column(Boolean, default=False)
    removed_reason: Mapped[str | None] = mapped_column(Text)
    narrative: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_to_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class SectionContentVersion(Base):
    __tablename__ = "section_content_versions"
    __table_args__ = (UniqueConstraint("section_id", "content_type", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("report_sections.id", ondelete="CASCADE"), index=True)
    content_type: Mapped[str] = mapped_column(String(50), default="CURRENT_OPERATIONS")
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(30), default="USER")
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ai_suggestion_id: Mapped[str | None] = mapped_column(ForeignKey("ai_suggestions.id", ondelete="SET NULL"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Response(Base, TimestampMixin):
    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("section_id", "prompt_id"), UniqueConstraint("report_id", "client_mutation_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("report_sections.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompt_definitions.id"))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    narrative: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(30), default="USER")
    version: Mapped[int] = mapped_column(Integer, default=1)
    client_mutation_id: Mapped[str | None] = mapped_column(String(36))
    authored_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Finding(Base, TimestampMixin):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("report_id", "client_mutation_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="SET NULL"), index=True)
    finding_type: Mapped[str] = mapped_column(String(40))
    statement: Mapped[str] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    source_type: Mapped[str] = mapped_column(String(30), default="LEGACY")
    client_mutation_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Metric(Base):
    __tablename__ = "metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(100))
    period: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceItem(Base, TimestampMixin):
    __tablename__ = "evidence_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="SET NULL"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(30))
    caption: Mapped[str | None] = mapped_column(Text)
    placement: Mapped[str] = mapped_column(String(30), default="INLINE")
    classification: Mapped[str] = mapped_column(String(30), default="CONFIDENTIAL")
    status: Mapped[str] = mapped_column(String(30), default="PENDING_UPLOAD")
    extraction_state: Mapped[str] = mapped_column(String(30), default="NOT_APPLICABLE")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    ai_inclusion_recommendation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class FileObject(Base):
    __tablename__ = "file_objects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_items.id", ondelete="CASCADE"), index=True)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    variant: Mapped[str] = mapped_column(String(40), default="ORIGINAL")
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    scan_state: Mapped[str] = mapped_column(String(30), default="NOT_SCANNED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Capability(Base, TimestampMixin):
    __tablename__ = "capabilities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    capability_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(250))
    domain: Mapped[str] = mapped_column(String(150), index=True)
    controlled_description: Mapped[str] = mapped_column(Text)
    typical_prerequisites: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED")
    source: Mapped[str | None] = mapped_column(Text)
    product_version: Mapped[str | None] = mapped_column(String(100))
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, default=1)


class CapabilityMapping(Base):
    __tablename__ = "capability_mappings"
    __table_args__ = (UniqueConstraint("finding_id", "capability_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="SET NULL"), index=True)
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(120), index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="FINDING")
    source_label: Mapped[str | None] = mapped_column(String(300))
    source_statement: Mapped[str | None] = mapped_column(Text)
    capability_id: Mapped[str] = mapped_column(ForeignKey("capabilities.id"))
    rationale: Mapped[str] = mapped_column(Text)
    prerequisites: Mapped[str | None] = mapped_column(Text)
    approval_state: Mapped[str] = mapped_column(String(20), default="PENDING")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    ai_suggestion_id: Mapped[str | None] = mapped_column(ForeignKey("ai_suggestions.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Benefit(Base):
    __tablename__ = "benefits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="SET NULL"), index=True)
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
    capability_mapping_id: Mapped[str | None] = mapped_column(ForeignKey("capability_mappings.id", ondelete="SET NULL"))
    source_ref: Mapped[str | None] = mapped_column(String(160), index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="MANUAL")
    source_label: Mapped[str | None] = mapped_column(String(300))
    source_statement: Mapped[str | None] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60), default="OPERATIONAL_EFFICIENCY")
    measure_type: Mapped[str] = mapped_column(String(30), default="QUALITATIVE")
    formula: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    approval_state: Mapped[str] = mapped_column(String(20), default="PENDING")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ai_suggestion_id: Mapped[str | None] = mapped_column(ForeignKey("ai_suggestions.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DemoPlanSettings(Base, TimestampMixin):
    __tablename__ = "demo_plan_settings"
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True)
    audience: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=45)
    additional_priorities: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class DemoSectionPriority(Base, TimestampMixin):
    __tablename__ = "demo_section_priorities"
    __table_args__ = (UniqueConstraint("report_id", "section_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("report_sections.id", ondelete="CASCADE"), index=True)
    priority: Mapped[str] = mapped_column(String(30), default="OPTIONAL")
    user_notes: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class DemoPlanVersion(Base):
    __tablename__ = "demo_plan_versions"
    __table_args__ = (UniqueConstraint("report_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_type: Mapped[str] = mapped_column(String(30), default="AI_ACCEPTED")
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ai_suggestion_id: Mapped[str | None] = mapped_column(ForeignKey("ai_suggestions.id", ondelete="SET NULL"), index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeEntry(Base, TimestampMixin):
    __tablename__ = "knowledge_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    source_ref: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(String(100), index=True)
    knowledge_kind: Mapped[str] = mapped_column(String(50), default="GENERAL", index=True)
    structured_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    title: Mapped[str] = mapped_column(String(250))
    process_module: Mapped[str | None] = mapped_column(String(100), index=True)
    content: Mapped[str] = mapped_column(Text)
    capability_id: Mapped[str | None] = mapped_column(ForeignKey("capabilities.id", ondelete="SET NULL"), index=True)
    prospect_id: Mapped[str | None] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    classification: Mapped[str] = mapped_column(String(30), default="INTERNAL")
    reusable_across_prospects: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_state: Mapped[str] = mapped_column(String(20), default="PENDING")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AiJob(Base):
    __tablename__ = "ai_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(50))
    instructions: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    policy_decision: Mapped[dict[str, Any]] = mapped_column(JSON)
    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    parent_suggestion_id: Mapped[str | None] = mapped_column(String(36), index=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    ai_job_id: Mapped[str] = mapped_column(ForeignKey("ai_jobs.id", ondelete="CASCADE"))
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(50))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    review_state: Mapped[str] = mapped_column(String(20), default="PENDING")
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    parent_suggestion_id: Mapped[str | None] = mapped_column(String(36), index=True)
    base_ai_text: Mapped[str | None] = mapped_column(Text)
    refinement_instruction: Mapped[str | None] = mapped_column(Text)
    superseded_by_suggestion_id: Mapped[str | None] = mapped_column(String(36), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="CASCADE"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("report_sections.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(36))
    target_version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))
    decided_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MergeOperation(Base):
    __tablename__ = "merge_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    target_report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"))
    source_report_ids: Mapped[list[str]] = mapped_column(JSON)
    conflict_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="PREVIEW")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MergeLineage(Base):
    __tablename__ = "merge_lineage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    merge_operation_id: Mapped[str] = mapped_column(ForeignKey("merge_operations.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(36))
    source_report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))
    source_type: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str] = mapped_column(String(36))
    source_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    report_revision: Mapped[int] = mapped_column(Integer)
    final_requested: Mapped[bool] = mapped_column(Boolean)
    passed: Mapped[bool] = mapped_column(Boolean)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    report_revision: Mapped[int] = mapped_column(Integer)
    publication_type: Mapped[str] = mapped_column(String(50))
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    validation_run_id: Mapped[str | None] = mapped_column(ForeignKey("validation_runs.id"))
    docx_file_id: Mapped[str | None] = mapped_column(ForeignKey("file_objects.id"))
    pdf_file_id: Mapped[str | None] = mapped_column(ForeignKey("file_objects.id"))
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    prospect_id: Mapped[str | None] = mapped_column(ForeignKey("prospects.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    request_id: Mapped[str | None] = mapped_column(String(100))
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    component: Mapped[str] = mapped_column(String(50), primary_key=True)
    app_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    storage_configured: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    queue_name: Mapped[str] = mapped_column(String(30), default="STANDARD", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
