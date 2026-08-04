from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=500)

    @field_validator("new_password")
    @classmethod
    def validate_complexity(cls, value: str) -> str:
        groups = [any(c.islower() for c in value), any(c.isupper() for c in value), any(c.isdigit() for c in value), any(not c.isalnum() for c in value)]
        if sum(groups) < 3:
            raise ValueError("Password must contain at least three of: lowercase, uppercase, number, symbol.")
        return value


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=10, max_length=500)
    roles: list[str] = Field(default_factory=lambda: ["CONTRIBUTOR"])

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        groups = [any(c.islower() for c in value), any(c.isupper() for c in value), any(c.isdigit() for c in value), any(not c.isalnum() for c in value)]
        if sum(groups) < 3:
            raise ValueError("Password must contain at least three of: lowercase, uppercase, number, symbol.")
        return value


class AdminUserDeleteRequest(BaseModel):
    replacement_user_id: str | None = None


class ProspectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=150)
    opportunity: str | None = None


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    timezone: str | None = Field(default=None, max_length=100)


class EngagementCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    site_id: str | None = None
    survey_date: date | None = None
    objectives: str | None = None


class ProspectOnboardingEngagement(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    survey_date: date | None = None
    objectives: str | None = None


class ProspectOnboardingCreate(BaseModel):
    prospect: ProspectCreate
    site: SiteCreate | None = None
    engagement: ProspectOnboardingEngagement | None = None


class ReportCreate(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    engagement_id: str
    site_id: str | None = None
    report_template_id: str | None = None
    report_kind: Literal["CAPTURE", "CONSOLIDATED"] = "CAPTURE"


class ReportUpdate(BaseModel):
    state: Literal["DRAFT", "READY_FOR_REVIEW"]


class SectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    process_module: str | None = Field(default=None, max_length=100)
    required_on_final: bool = False


class SectionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=250)
    narrative: str | None = None
    state: Literal["ACTIVE", "REMOVED"] | None = None
    removed_reason: str | None = None
    display_order: int | None = None
    expected_version: int | None = Field(default=None, ge=1)


class SectionContentUpsert(BaseModel):
    content_type: Literal["CLOUD_INVENTORY_APPROACH"] = "CLOUD_INVENTORY_APPROACH"
    text: str = Field(default="", max_length=50000)
    expected_version: int | None = Field(default=None, ge=1)


class ReportContentUpsert(BaseModel):
    content_type: Literal["EXECUTIVE_SUMMARY"] = "EXECUTIVE_SUMMARY"
    text: str = Field(default="", max_length=50000)
    expected_version: int | None = Field(default=None, ge=1)


class ResponseUpsert(BaseModel):
    prompt_id: str
    narrative: str = ""
    payload: dict[str, Any] | None = None
    client_mutation_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)


class QuickCaptureRequest(BaseModel):
    section_id: str
    note: str = Field(min_length=1)
    finding_type: str = "OBSERVATION"
    impact: str | None = None
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    client_mutation_id: str | None = None


class FindingCreate(BaseModel):
    section_id: str | None = None
    finding_type: str = Field(min_length=1, max_length=40)
    statement: str = Field(min_length=1)
    impact: str | None = None
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    client_mutation_id: str | None = None


class MetricCreate(BaseModel):
    section_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    period: str | None = None
    source: str | None = None
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"


class CapabilityMappingCreate(BaseModel):
    finding_id: str | None = None
    section_id: str | None = None
    source_ref: str | None = Field(default=None, max_length=120)
    capability_id: str
    rationale: str = Field(min_length=1)
    prerequisites: str | None = None

    @model_validator(mode="after")
    def validate_mapping_source(self):
        if not self.finding_id and not self.source_ref:
            raise ValueError("A finding or operational observation source is required.")
        return self


class BenefitCreate(BaseModel):
    section_id: str | None = None
    finding_id: str | None = None
    capability_mapping_id: str | None = None
    source_ref: str | None = Field(default=None, max_length=160)
    statement: str = Field(min_length=1)
    category: Literal[
        "OPERATIONAL_EFFICIENCY",
        "INVENTORY_VISIBILITY",
        "ACCURACY_CONTROL",
        "CUSTOMER_SERVICE",
        "WORKFORCE_PRODUCTIVITY",
        "COMPLIANCE_TRACEABILITY",
        "MANAGEMENT_VISIBILITY",
        "SCALABILITY",
    ] = "OPERATIONAL_EFFICIENCY"
    measure_type: Literal["QUALITATIVE", "QUANTITATIVE"] = "QUALITATIVE"
    formula: str | None = None
    assumptions: str | None = None
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"


class DemoPlanSettingsUpsert(BaseModel):
    audience: str = Field(default="", max_length=4000)
    duration_minutes: int = Field(default=45, ge=10, le=480)
    additional_priorities: str = Field(default="", max_length=10000)
    expected_version: int | None = Field(default=None, ge=1)


class DemoSectionPriorityUpsert(BaseModel):
    priority: Literal["MUST_SHOW", "SHOULD_SHOW", "OPTIONAL", "DO_NOT_SHOW"] = "OPTIONAL"
    user_notes: str = Field(default="", max_length=10000)
    constraints: str = Field(default="", max_length=10000)
    estimated_minutes: int | None = Field(default=None, ge=1, le=240)
    expected_version: int | None = Field(default=None, ge=1)


class ReviewDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    note: str | None = None
    selected_item_indexes: list[int] = Field(default_factory=list, max_length=100)


class ValidationRequest(BaseModel):
    final_requested: bool = False


class PublicationRequest(BaseModel):
    publication_type: Literal["FULL_DISCOVERY", "DEMO_BRIEF", "FOLLOW_UP_QUESTIONNAIRE"] = "FULL_DISCOVERY"
    is_final: bool = False


class MergeRequest(BaseModel):
    target_report_id: str
    source_report_ids: list[str] = Field(min_length=1)
    delete_sources_after_merge: bool = True


class AiRequest(BaseModel):
    section_id: str | None = None
    purpose: Literal[
        "NARRATIVE",
        "GAP_ANALYSIS",
        "CAPABILITY_RECOMMENDATION",
        "BENEFIT_DRAFT",
        "EXECUTIVE_SUMMARY",
        "ATTACHMENT_REVIEW",
        "OBSERVATION_ENHANCEMENT",
        "SOLUTION_APPROACH",
        "TARGETED_BENEFITS",
        "DEMO_PLAN",
        "REPORT_QUALITY_REVIEW",
    ]
    instructions: str | None = Field(default=None, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    parent_suggestion_id: str | None = None
    force_regenerate: bool = False



class BrandingUpdate(BaseModel):
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    heading_font: str | None = None
    body_font: str | None = None
    confidentiality_text: str | None = None
    draft_watermark: str | None = None
    footer_text: str | None = None
    photo_size_uom: Literal["INCHES", "CENTIMETRES"] | None = None
    landscape_photo_width: float | None = Field(default=None, gt=0.1, le=30)
    landscape_photo_height: float | None = Field(default=None, gt=0.1, le=30)
    portrait_photo_width: float | None = Field(default=None, gt=0.1, le=30)
    portrait_photo_height: float | None = Field(default=None, gt=0.1, le=30)


class EvidenceBulkAction(BaseModel):
    action: Literal["MOVE", "DELETE"]
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    target_section_id: str | None = None


class CapabilityCreate(BaseModel):
    capability_code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=250)
    domain: str = Field(min_length=2, max_length=150)
    controlled_description: str = Field(min_length=2)
    typical_prerequisites: str | None = None
    limitations: str | None = None
    status: Literal["PROPOSED", "APPROVED", "RETIRED"] = "PROPOSED"
    source: str | None = None
    product_version: str | None = Field(default=None, max_length=100)
    review_due_at: datetime | None = None


class CapabilityUpdate(BaseModel):
    capability_code: str | None = Field(default=None, min_length=2, max_length=50)
    name: str | None = Field(default=None, min_length=2, max_length=250)
    domain: str | None = Field(default=None, min_length=2, max_length=150)
    controlled_description: str | None = Field(default=None, min_length=2)
    typical_prerequisites: str | None = None
    limitations: str | None = None
    status: Literal["PROPOSED", "APPROVED", "RETIRED"] | None = None
    source: str | None = None
    product_version: str | None = Field(default=None, max_length=100)
    review_due_at: datetime | None = None
    expected_version: int | None = Field(default=None, ge=1)


class CommentCreate(BaseModel):
    section_id: str | None = None
    body: str = Field(min_length=1, max_length=10000)


class KnowledgeEntryCreate(BaseModel):
    source_type: str = Field(min_length=2, max_length=50)
    source_ref: str | None = None
    source_version: str | None = Field(default=None, max_length=100)
    knowledge_kind: str = Field(default="GENERAL", min_length=2, max_length=50)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    title: str = Field(min_length=2, max_length=250)
    process_module: str | None = Field(default=None, max_length=100)
    content: str = Field(min_length=2)
    capability_id: str | None = None
    prospect_id: str | None = None
    classification: Literal["INTERNAL", "CONFIDENTIAL", "PUBLIC"] = "INTERNAL"
    reusable_across_prospects: bool = False
    review_due_at: datetime | None = None
    expires_at: datetime | None = None


class KnowledgeEntryReview(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reusable_across_prospects: bool | None = None
    title: str | None = Field(default=None, min_length=2, max_length=250)
    content: str | None = Field(default=None, min_length=2)
    review_due_at: datetime | None = None
    expires_at: datetime | None = None
    note: str | None = None


class ProspectArchiveRequest(BaseModel):
    reason: str | None = None


class ProspectDeleteRequest(BaseModel):
    confirm_name: str
    confirm_exported: bool = False


class ReportDeleteRequest(BaseModel):
    confirm_title: str


class EvidenceReviewRequest(BaseModel):
    include_in_report: bool
    rationale: str | None = None
