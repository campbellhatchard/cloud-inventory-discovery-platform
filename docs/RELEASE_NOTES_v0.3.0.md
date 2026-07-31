# Release Notes — v0.3.0

## Summary

Version 0.3.0 introduces Quick Entry as the primary onsite field-capture workflow. It reduces navigation during a site survey while preserving the existing structured report, evidence lineage, review, and publication model.

## Added

- Quick Entry screen before Opportunity Overview.
- Persistent per-report Area of Operation selection.
- Large multiline Quick Field Capture note area.
- Separate Take Photo and Choose File actions.
- Native rear-camera hint for supported phones and tablets.
- Automatic routing of notes and evidence into destination report sections.
- New Printing report section and `PRINTING` process module.
- Alembic migration to backfill Printing into active reports without modifying finalized reports.
- Regression tests for Quick Entry contracts, Printing prompts, routing, and evidence section-state updates.

## Changed

- Removed section-level quick capture forms to establish one primary capture workflow.
- Removed section-level evidence upload and placement controls.
- Detailed sections remain the review, refinement, approval, and publication workspace.
- Evidence upload now moves a destination section from `NOT_STARTED` to `IN_PROGRESS`.
- Service-worker cache and application identity advanced to `0.3.0`.

## Compatibility

- Database migration: required.
- Existing findings and evidence: unchanged.
- Existing finalized reports: unchanged.
- Existing non-finalized reports: receive the new Printing section.
- Object storage format: unchanged.
- Environment variables: no new variables.

## Validation evidence

- Automated tests: 20 passed.
- Python compilation: passed.
- JavaScript syntax: passed.
- OpenAPI generation: passed.
- DOCX/PDF workflow regression: passed.
- Migration backfill simulation: passed for draft and finalized reports.

## Development branch

`feature/quick-entry-v0.3.0`, based on locked branch `baseline-v0.2.1`.
