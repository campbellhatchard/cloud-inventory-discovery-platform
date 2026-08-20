# Deployment Guide — v0.8.8

## Locked baseline

- Source branch: `staging`
- Required baseline version: `0.8.7`
- Required baseline commit: `290c51583c70e6c7005785f3f8968837b7766225`
- Baseline database revision: `l72i5d1g9e32`
- v0.8.8 database revision: `m83j6e2h0f43`
- Feature branch: `feature/case-insensitive-usernames-v0.8.8`

## Deployment order

1. Place the v0.8.8 implementation package and installer directly in Downloads; do not extract the ZIP.
2. Run the PowerShell installer with `-PromoteToStaging`.
3. The installer verifies the exact staging SHA, applies the package to the feature branch, and runs the full Windows validation gate before commit or push.
4. Sync the Render Blueprint if required. No new environment variables are introduced.
5. Deploy **Web first** so Alembic runs migration `m83j6e2h0f43`.
6. Confirm Web reports application version `0.8.8` and `/readyz` is healthy.
7. Verify mixed-case username login and duplicate rejection.
8. Deploy Worker and confirm version `0.8.8`.

## Collision protection

Before adding the normalized username column, migration `m83j6e2h0f43` scans existing usernames using the same case-folding rule as the application. If two existing records normalize to the same value, migration stops before altering the schema. Resolve the duplicate account names deliberately and redeploy; do not bypass the check.

## Rollback

Application rollback requires database downgrade from `m83j6e2h0f43` to `l72i5d1g9e32`, which drops the normalized username key. A database backup should be retained before production deployment.
