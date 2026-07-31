# Baseline Manifest - v0.2.1

## Canonical baseline

- Repository: `campbellhatchard/cloud-inventory-discovery-platform`
- Baseline branch: `baseline-v0.2.1`
- Baseline commit: `7a36fa0527e97191fa46147e663b59dc8ef282f2`
- Software version: `0.2.1`
- Specification version: `1.1`
- Date locked: 31 July 2026

## Required baseline files

- Application source under `app/`
- Alembic configuration and migrations
- Tests under `tests/`
- Render Blueprint files
- `scripts/render-predeploy.sh`
- PowerShell validation/deployment toolkit
- Dockerfile and dependency manifests
- Controlled capability and question seed assets
- Architecture, security, deployment, operations, user guide, specification, release notes, acceptance report, and OpenAPI documents

## Excluded from the baseline

- `.env` and environment-specific secret files
- API keys, object-storage credentials, administrator passwords, database credentials, and Render API credentials
- Runtime databases, generated reports, uploaded evidence, object-store content, caches, local virtual environments, and deployment output

## Change-control minimum

Every enhancement must record:

1. Requirement IDs affected.
2. Database migration impact.
3. API and UI impact.
4. Security, privacy, retention, and AI impact.
5. Regression tests added or amended.
6. Deployment or rollback changes.
7. Updated software and document versions.
