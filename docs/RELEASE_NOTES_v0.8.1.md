# Release Notes — v0.8.1

## Report Quality, Readiness and Operational Governance

### Added

- Content-driven report readiness dashboard with section-level `READY`, `PARTIAL`, `REVIEW_REQUIRED`, `MISSING`, and `NOT_APPLICABLE` states.
- Direct navigation from readiness gaps to the affected operational section.
- Whole-report AI quality review covering completeness, consistency, unsupported claims, duplication, solution coverage, benefit support, demo alignment, and follow-up questions.
- Human disposition of quality reviews without automatic report rewriting.
- Version-controlled manual and AI-assisted Executive Summary.
- Executive Summary factual-support verification, natural-language refinement, side-by-side comparison, read-aloud, acceptance, and version history.
- Executive Summary in Full Discovery DOCX/PDF output.
- Visible source and claim traceability by operational section.
- Report-level reviewer work queue.
- Cross-report Administration review queue.
- Administration operational dashboard for AI jobs, worker heartbeat, storage status, publication status, and lifecycle review counts.
- Worker heartbeat persisted to PostgreSQL.
- Capability product-version applicability and review lifecycle fields.
- Knowledge review and expiration lifecycle fields.

### Changed

- Draft/final validation now warns when the Executive Summary or content-chain elements are incomplete without making empty optional sections mandatory.
- Reviewed or dismissed report-quality recommendations leave the active work queue.
- Application, Blueprint, package, service-worker, and OpenAPI versions updated to 0.8.1.

### Governance

- Whole-report AI review is advisory only.
- Executive Summary acceptance is blocked when unsupported claims remain.
- Stale Executive Summary suggestions are rejected when the report revision changes.
- Operational health endpoints do not expose credentials or secret values.
- Existing human approval requirements for capabilities, mappings, benefits, knowledge, and publication remain in force.

### Database

Alembic revision: `f16c9d5a3e66_report_quality_readiness_governance.py`.

### Environment impact

No new environment variables are required. Existing OpenAI, PostgreSQL, Cloudflare R2, and LibreOffice configuration is reused. Web and Worker must both be deployed so the worker heartbeat and new AI job purposes run on the same version.
