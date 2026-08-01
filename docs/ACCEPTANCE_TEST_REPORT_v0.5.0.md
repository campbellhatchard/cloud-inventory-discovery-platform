# Acceptance Test Report — v0.5.0

## Build
Cloud Inventory Site Discovery Platform v0.5.0 — Report Review & Usability.

Baseline: `baseline-v0.4.1` at `da6a026a382ce625ad5656ab4ec56c4ce3c651b7`.

## Validation completed in build environment
- JavaScript syntax validation (`node --check app/static/app.js`): **PASS**
- Python compilation (`python -m compileall app`): **PASS**
- Automated pytest suite: **30 passed**
- Alembic fresh-database upgrade through `f50a7c19d8e2`: **PASS**
- OpenAPI document generation: **PASS**

Ruff was not installed in the artifact-build container. The supplied PowerShell installer runs the repository's `Deploy.ps1 -Action Validate`, which creates an isolated validation environment, installs the development requirements, runs Ruff, the full pytest suite, Python compilation, and the existing deployment validation contract before it creates or pushes a Git commit.

## Functional coverage added
- General Discussion Points is present between General Operational Observations and Receiving.
- All section and prompt `required_on_final` flags are false for newly seeded reports.
- The retired generic purpose question is not returned to the active UI.
- Empty optional sections do not block final validation.
- Populated sections still require Ready for review or Approved before final publication.
- Prospect logo upload/download round trip succeeds under local object storage.
- Report page, centralized validation/publication controls, and stable-navigation contracts are asserted.
- Migration contract asserts existing-report backfill and required-flag removal.

## Staging dependency
Prospect logos, evidence, generated documents, exports, and other object-storage functions continue to depend on valid staging S3/R2 configuration. Prospect logo upload returns a controlled 503 when object storage is unavailable.
