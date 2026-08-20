# Acceptance Test Report - v0.7.0

## Result

**PASS — package validation complete.**

## Automated validation

- Pytest: **53 passed**.
- v0.7.0 solution-intelligence regression tests: **7 passed**.
- JavaScript syntax: `node --check app/static/app.js` passed.
- Python compilation: `python -m compileall -q app alembic` passed.
- OpenAPI document regenerated successfully as version 0.7.0.
- Fresh SQLite migration from initial schema to `d94a7b3e1c44` passed.
- Upgrade test from v0.6.1 migration head `c83f2a9d6e32` to `d94a7b3e1c44` confirmed existing finding-based mapping source backfill.

## Functional regression coverage

The v0.7.0 test suite verifies:

1. Section narrative can be mapped as a GENERAL_OBSERVATION without creating a Finding.
2. Guided responses are exposed to solution intelligence as Observations.
3. Explicit Findings retain their original finding type.
4. Approved capabilities and approved knowledge enter the controlled AI context.
5. Accepted solution AI creates a current `CLOUD_INVENTORY_APPROACH` version and approved source-aware mappings.
6. A solution proposal becomes stale and cannot be accepted after operational content changes.
7. Historical knowledge remains unavailable to AI while PENDING and becomes available after approval.
8. Generated DOCX output contains Cloud Inventory Approach and mapped-functionality source traceability.
9. Frontend contracts for generation, refinement, acceptance, source-aware Findings messaging, and knowledge import are present.

## Deployment gate

The Windows installer still runs `Deploy.ps1 -Action Validate -Environment staging -Region ohio` before commit/push. That remains the authoritative pre-deployment gate, including Ruff where installed/configured in the local deployment toolchain.
