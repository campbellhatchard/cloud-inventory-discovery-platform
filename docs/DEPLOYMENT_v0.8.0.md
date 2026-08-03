# Deployment Guide — v0.8.0
## Targeted Benefits and Demo Orchestration

## Baseline

- Branch: `baseline-v0.7.1`
- Commit: `32bbf9a608ffd4aab4954637463f52d9cc76ab91`

## Feature branch

`feature/targeted-benefits-demo-orchestration-v0.8.0`

## Database

The Web service pre-deploy command runs Alembic revision `e05b8c4f2d55`. Back up the staging database before deployment if required by your normal operating procedure.

## Environment variables

No new environment variables are introduced. Retain the existing PostgreSQL, Cloudflare R2, OpenAI, AI policy, session, and application settings on both Web and Worker services.

## Deployment sequence

1. Download the v0.8.0 installer and source ZIP to the Windows Downloads folder.
2. Run the installer with `-PromoteToStaging`.
3. Confirm complete repository validation passes before commit and push.
4. In Render, run Sync Blueprint.
5. Manually deploy the latest staging commit to the Web service.
6. Manually deploy the latest staging commit to the Worker service.
7. Confirm the Web pre-deploy migration completes through `e05b8c4f2d55`.
8. Run the staging proving checklist in the Acceptance Test Report.

## Rollback

Application rollback can use the previous locked `baseline-v0.7.1` image/commit. Because v0.8.0 introduces new tables and nullable Benefit columns, leaving the forward database migration in place is generally safer than downgrading during an application rollback. Perform an Alembic downgrade only under a controlled database recovery plan.
