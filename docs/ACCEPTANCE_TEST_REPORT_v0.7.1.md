# Acceptance Test Report — v0.7.1

## Automated validation

- Full pytest suite: **56 passed**
- Dedicated v0.7.1 tests: **3 passed**
- JavaScript syntax validation: passed
- Python compilation: passed
- OpenAPI regeneration: version `0.7.1`; manual section-content route present
- Fresh Alembic upgrade through `d94a7b3e1c44`: passed

## Functional coverage

- First manual Cloud Inventory approach save creates version 1 with source type USER.
- A subsequent edit creates a new current version and retains the previous version.
- A stale expected version is rejected with HTTP 409 and current text/version details.
- Report API returns the current manually entered approach.
- Section UI contains direct-entry editor, capability mapping action, and AI generation action.
- AI generation flushes unsaved manual text before creating the AI request.

## Installer gate

The Windows installer runs the complete repository `Deploy.ps1 -Action Validate` workflow, including Ruff, before commit or push.
