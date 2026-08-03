# Report Quality, Readiness and Operational Governance — v0.8.1

## Purpose

v0.8.1 adds the control layer required to assess whether a discovery report is complete, internally consistent, evidence-based, and ready for customer or Presales use. It builds on the locked v0.8.0 Targeted Benefits and Demo Orchestration baseline.

## Functional scope

### Content-driven readiness dashboard

The Report workspace calculates readiness from actual report content. It does not require section assignment or a manually selected section status.

Each active operational section is assessed for:

- current-operations evidence from narrative, guided responses, or findings;
- a current Cloud Inventory Approach;
- approved capability mappings;
- approved targeted benefits;
- pending mappings or benefits requiring review;
- accepted demo-plan coverage where the area is Must Show or Should Show.

The calculated section states are `READY`, `PARTIAL`, `REVIEW_REQUIRED`, `MISSING`, and `NOT_APPLICABLE`.

### Whole-report AI quality review

A reviewer can request a report-level AI assessment. The worker reviews the complete discovery packet for:

- completeness and internal consistency;
- unsupported or contradictory claims;
- duplicated content;
- findings without solution coverage;
- approaches without approved mappings;
- benefits without adequate sources;
- demo-plan alignment;
- information gaps that should become follow-up questions.

The review produces recommendations only. It cannot directly rewrite, approve, or publish report content. The reviewer can mark the review addressed or dismiss it.

### Executive summary

The Report workspace includes a version-controlled customer-facing Executive Summary. A user may:

- enter and autosave the summary manually;
- generate a source-grounded AI proposal;
- compare the current and proposed versions;
- refine the proposal through natural-language instructions;
- listen to the proposed summary using browser speech synthesis;
- accept only a summary that passes factual-support verification;
- review all previous manual and AI-accepted versions.

The accepted summary is inserted into Full Discovery Word and PDF output after the table of contents.

### Source and claim traceability

The reviewer can inspect accepted report claims by section. Claims are classified as:

- `DIRECT_OBSERVATION`;
- `USER_INTERPRETATION`;
- `APPROVED_PRODUCT_STATEMENT`;
- `EXPECTED_QUALITATIVE_BENEFIT`;
- `SUPPORTED_QUANTITATIVE_CLAIM`;
- `REQUIRES_REVIEW`.

The traceability view exposes the stored source references without exposing system credentials or hidden AI configuration.

### Reviewer work queues

The report-level queue consolidates:

- pending capability mappings;
- pending benefits;
- pending or stale AI suggestions;
- unresolved comments;
- failed publications;
- unresolved whole-report quality issues.

Administration adds a cross-report queue and provides direct navigation to the report or operational section requiring attention.

### Operational health dashboard

Administration displays safe operational signals for:

- AI job status and average processing duration;
- aggregate AI token/call usage where supplied by the provider;
- recent AI failures;
- generic worker queue status;
- Web application version;
- worker heartbeat, version, last-seen time, and storage readiness;
- syntactic object-storage readiness;
- last successful publication;
- capability and knowledge lifecycle items due for review.

Credentials, access keys, API keys, and secret values are never returned by these endpoints.

### Capability and knowledge lifecycle

Capabilities now support:

- product-version applicability;
- next-review date;
- last-reviewed date and reviewer.

Knowledge entries now support:

- next-review date;
- expiration date;
- last-reviewed date and reviewer.

Expired and review-due records are surfaced in Administration. Approval and reuse controls remain unchanged.

## Data model

Alembic revision `f16c9d5a3e66` adds:

- `report_content_versions`;
- `worker_heartbeats`;
- capability product-version and review lifecycle fields;
- knowledge review and expiration lifecycle fields.

## AI governance

Two new AI purposes are introduced:

- `REPORT_QUALITY_REVIEW`;
- `EXECUTIVE_SUMMARY`.

Both use the existing confidential-content policy gate and background worker. Executive summaries receive a second factual-support verification pass and cannot be accepted when unsupported claims remain. Whole-report reviews are recommendations and always require human disposition.

## Publication behavior

Full Discovery DOCX/PDF output includes the current Executive Summary. Existing table-of-contents, footer, logo, confidentiality, indentation, branding, draft, and R2 publication rules remain unchanged.

## Out of scope

v0.8.1 does not introduce Cloud Inventory MCP connectivity, live product-system access, automated report rewriting, autonomous approval, production-system transactions, or access to customer production data.
