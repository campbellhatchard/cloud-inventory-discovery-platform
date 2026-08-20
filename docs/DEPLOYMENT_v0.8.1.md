# Deployment Guide — v0.8.1

## Baseline

- Branch: `baseline-v0.8.0`
- Commit: `fef44a0f2ff83229eb9e25c71b5dd9f1de2c2cee`

## Target feature branch

`feature/report-quality-readiness-governance-v0.8.1`

## Installer behavior

The supplied PowerShell installer:

1. moves v0.8.1 release files from Downloads into the versioned installer folder;
2. validates the source SHA-256 when the manifest is present;
3. refuses a dirty local repository;
4. verifies the exact locked v0.8.0 baseline commit and application version;
5. creates the v0.8.1 feature branch from the locked baseline;
6. applies the source package;
7. locates LibreOffice;
8. runs `Deploy.ps1 -Action Validate -Environment staging -Region ohio`;
9. commits and pushes only after validation succeeds;
10. optionally fast-forwards and pushes `staging`.

## Render deployment

After successful GitHub promotion:

1. Sync the Render Blueprint to update `APP_VERSION` to `0.8.1`.
2. Deploy the latest staging commit to the Web service.
3. Deploy the latest staging commit to the Worker service.
4. Confirm the Web service completes Alembic revision `f16c9d5a3e66`.
5. Confirm the Worker starts and Administration displays a current heartbeat.

No new environment variables are required. Retain the existing PostgreSQL, Cloudflare R2, OpenAI, AI policy, and LibreOffice settings.

## Staging smoke test

1. Open an existing discovery report and confirm the Executive Summary and Report Quality and Readiness cards appear.
2. Enter an Executive Summary and confirm autosave/version history.
3. Generate and accept an AI Executive Summary.
4. Select Review Entire Report and confirm recommendations appear without changing report content.
5. Open traceability and confirm accepted observations, solution statements, mappings, and benefits are classified.
6. Confirm the reviewer queue links to the relevant report section.
7. Open Administration → Operations and confirm the Worker heartbeat is current and no secrets are displayed.
8. Generate a Draft Word document and confirm the Executive Summary appears after the table of contents.
