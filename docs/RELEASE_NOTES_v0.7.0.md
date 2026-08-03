# Release Notes - v0.7.0

## Cloud Inventory Solution Intelligence

v0.7.0 builds on the locked v0.6.1 baseline and adds governed Cloud Inventory solution guidance to each operational discovery section.

### New functionality

- Added a dedicated **Cloud Inventory Approach** block to operational sections.
- Added AI generation, side-by-side review, natural-language refinement, read-aloud, verification, acceptance, and version history for solution wording.
- Added source-aware capability mappings that can map approved functionality to either formal Findings or ordinary current-operations notes.
- General narrative and guided responses are treated as **Observations** for functionality mapping without changing or duplicating their original content.
- Explicit Findings continue to retain their recorded classification: Observation, Pain Point, Risk, Gap, Strength, Opportunity, or other configured type.
- Added historical-document knowledge import and administrative approval workflow.
- Restricted solution AI to approved capabilities and approved historical knowledge.
- Added product-claim verification and stale-source protection before AI solution text can be accepted.
- Added Cloud Inventory Approach and mapping source traceability to DOCX/PDF report generation.

### Governance

- Historical document imports enter PENDING review and are not usable by solution AI until approved.
- Prospect-specific knowledge remains prospect-specific unless explicitly de-identified and approved for reusable use.
- No new capability is inferred or approved by AI.
- General notes are mapping sources, not automatically created Findings.

### Environment impact

No new environment variables are required. Existing v0.6.1 OpenAI, R2, database, and LibreOffice configuration is reused.

The web service and worker should both be deployed because the worker processes `SOLUTION_APPROACH` AI jobs.
