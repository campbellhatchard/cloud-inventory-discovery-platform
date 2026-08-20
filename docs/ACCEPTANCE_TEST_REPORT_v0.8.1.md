# Acceptance Test Report — v0.8.1

## Scope

Report Quality, Readiness and Operational Governance built from locked baseline `baseline-v0.8.0` at commit `fef44a0f2ff83229eb9e25c71b5dd9f1de2c2cee`.

## Automated validation

- Full pytest suite: **73 passed**.
- Dedicated v0.8.1 tests: **9 passed**.
- Python compile-all across `app` and `alembic`: passed.
- JavaScript syntax validation with `node --check app/static/app.js`: passed.
- Fresh SQLite Alembic migration from initial revision through `f16c9d5a3e66`: passed.
- Upgrade migration from v0.8.0 revision `e05b8c4f2d55` to `f16c9d5a3e66`: passed.
- OpenAPI regenerated with application/API version `0.8.1`.

## Acceptance coverage

The dedicated regression suite confirms:

1. Manual Executive Summary versioning and optimistic concurrency.
2. AI Executive Summary acceptance into controlled report content.
3. Content-driven readiness state calculation.
4. Reviewer queue and source-aware traceability.
5. Whole-report quality issues in the review queue.
6. Safe worker heartbeat and Administration operations payloads without secret fields.
7. Executive Summary inclusion in Full Discovery DOCX output.
8. Frontend, model, and migration release markers.
9. Expired knowledge is excluded from Solution AI grounding.

## Packaging-environment limitation

Ruff was not installed in the packaging runtime. The Windows installer therefore treats the existing `Deploy.ps1 -Action Validate` process as the release gate. It will stop before commit or push if the repository's pinned Ruff, pytest, compilation, secret scan, Blueprint generation, or other deployment checks fail. Alembic and OpenAPI were validated separately during packaging.

## Result

The source package is suitable for controlled staging deployment, subject to the complete Windows validation gate and the user's staging acceptance test.
