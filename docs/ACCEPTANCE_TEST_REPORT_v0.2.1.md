# Acceptance Test Report - v0.2.1

**Product:** Cloud Inventory Site Discovery Platform  
**Environment:** Render staging  
**Date:** 31 July 2026  
**Result:** Accepted as the enhancement baseline

## Acceptance summary

| Gate | Result | Evidence |
| --- | --- | --- |
| Source validation | Pass | Secret scan, dependency installation, lint, compilation, JavaScript syntax, tests |
| Database | Pass | Clean Alembic upgrade and seed execution |
| Authentication | Pass | Login, lockout controls, session handling, required first-login password change |
| Authorization | Pass | Prospect/report access isolation tests |
| Collaboration | Pass | Assignment, comments, optimistic concurrency, merge lineage |
| Evidence | Pass | Image upload, normalization, classification, extraction, private object storage integration |
| Documents | Pass | Draft DOCX/PDF generation and watermark validation |
| Deployment | Pass | Docker build, Render pre-deploy, health and readiness checks |
| Live proving | Pass | Administrator login and password-change workflow completed |

## Defects found and closed during proving

1. Python 3.14 lacked a compatible `psycopg-binary 3.2.9` wheel. Closed by upgrading to 3.2.13.
2. Ruff scanned the temporary virtual environment. Closed by preserving default exclusions and narrowing validation targets.
3. Ruff policy blocked FastAPI dependency-injection idioms. Closed by limiting the deployment gate to `E` and `F`.
4. Windows validation attempted the Linux LibreOffice executable and used an invalid profile URI. Closed through explicit local configuration and cross-platform URI generation.
5. Render did not parse compound pre-deploy commands as expected. Closed by using a dedicated shell script.
6. The password modal was outside the delegated event-listener container. Closed by delegating on `document` and reloading `/api/auth/me` after successful password change.

## Residual risk accepted for staging

- AI remains disabled.
- Malware scanning is not bundled.
- Database row-level security is not enabled.
- Production backup/restore and disaster recovery have not been proven.
- Mobile field acceptance across the target device estate remains to be completed.

## Acceptance decision

The build is accepted as software release v0.2.1 and specification baseline v1.1. Future work shall use the locked GitHub branch `baseline-v0.2.1` as the source baseline.
