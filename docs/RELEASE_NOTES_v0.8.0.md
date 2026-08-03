# Release Notes — v0.8.0
## Targeted Benefits and Demo Orchestration

### Added

- Targeted Benefits workspace in each operational section.
- Manual benefits linked to approved functionality mappings, findings, general observations, guided responses, or metrics.
- AI-generated benefits with source traceability, natural-language refinement, selectable acceptance, and verification.
- Benefit categories, confidence, approver, source snapshot, and AI lineage.
- Quantitative-claim gate requiring a recorded metric, formula, and assumptions.
- Report-level Demo Preparation settings for audience, duration, priorities, and preparation notes.
- Section-level Must Show, Should Show, Optional, and Do Not Show priorities.
- Section demo notes, constraints, and estimated time.
- AI-generated demonstration plan with ordered flow, scenarios, value statements, talking points, questions, and claims to avoid.
- Version history for accepted demo plans.
- Structured Demo Brief Word/PDF output based on the accepted demo plan.

### Changed

- General notes continue to function as Observations when benefits and demonstration functionality are assessed.
- Approved benefits are now section-aware and preserve their operational or mapping source.
- Report content detection includes sections containing approved benefits.
- Demo Brief generation prioritizes the current accepted structured plan.
- Application, Blueprint, package, and service-worker versions updated to 0.8.0.

### Governance

- AI cannot invent numerical benefits.
- AI benefit acceptance creates PENDING benefits; reviewer approval remains required.
- Must Show and Do Not Show priorities are enforced in demo-plan verification.
- Every demo flow item must trace to an approved capability mapping.
- Stale AI suggestions are rejected when report or section source content has changed.

### Database

Alembic revision: `e05b8c4f2d55_targeted_benefits_demo_orchestration.py`.
