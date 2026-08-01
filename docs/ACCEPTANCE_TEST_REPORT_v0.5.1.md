# Acceptance Test Report — v0.5.1

## Build
Cloud Inventory Site Discovery Platform v0.5.1 — Collaborative Capture & R2 Storage Readiness.

## Automated validation performed in build environment
- Pytest: **34 passed**.
- JavaScript syntax: `node --check app/static/app.js` passed.
- Python compilation: `compileall` passed for application and Alembic sources.
- Alembic clean-database upgrade: passed through revision `a61d9e7c4b10`.
- OpenAPI document regenerated at application version `0.5.1`.
- Direct Draft Word and Draft PDF were tested with the Cloudflare placeholder endpoint and completed without requiring R2.
- Existing local-storage publication test generated and downloaded both DOCX and PDF successfully.

## Deployment gate
The Windows installer runs the repository's full `Deploy.ps1 -Action Validate -Environment staging -Region ohio` validation before creating a Git commit or pushing to GitHub. This includes Ruff in the repository's standard validation sequence. If that validation fails, the installer stops without commit/push.

## Functional acceptance coverage
- Sections use internal ACTIVE/REMOVED lifecycle only.
- Section assignment is absent from API response/UI workflow.
- Capturing a response does not change section workflow status.
- Report-level Ready for review state controls final validation.
- Report preview is content-driven.
- R2 placeholder is detected as a storage configuration error.
- Draft DOCX/PDF generation remains available without R2.
