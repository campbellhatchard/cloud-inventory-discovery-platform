# Release Notes - v0.2.1

## Baseline release

Version 0.2.1 is the first validated, live Render staging baseline for the Cloud Inventory Site Discovery Platform. It consolidates the v0.2.0 deployment package with the stabilization corrections required during real GitHub, Windows validation, Render deployment, and first-login proving.

## Stabilization changes

- Updated `psycopg[binary]` from `3.2.9` to `3.2.13`.
- Corrected Ruff exclusions and narrowed the deployment gate to Python `E` and `F` findings.
- Limited Ruff validation to application, tests, scripts, and Alembic environment source.
- Corrected LibreOffice temporary profile URI construction for Windows and Linux.
- Added `scripts/render-predeploy.sh` and configured Render to invoke it directly.
- Corrected forced-password modal event delegation and authoritative session refresh.
- Advanced the service-worker cache and application version to `0.2.1`.
- Added baseline regression tests and release-governance documents.

## Validation evidence

- Automated application tests: pass.
- Python compilation: pass.
- JavaScript syntax: pass.
- Alembic migration and seed: pass.
- DOCX/PDF generation: pass.
- Render Docker build: pass.
- Render pre-deploy: pass.
- Web service health/readiness: pass.
- First login and required password change: pass.

## Baseline identity

- Repository: `campbellhatchard/cloud-inventory-discovery-platform`
- Live branch: `staging`
- Locked branch: `baseline-v0.2.1`
- Baseline commit: `7a36fa0527e97191fa46147e663b59dc8ef282f2`
- Specification: v1.1

## Remaining controls

Production remains gated pending backup/restore testing, target-device field acceptance, organization approval of branding/legal content, malware-scanning decision, and approval of any confidential AI configuration.
