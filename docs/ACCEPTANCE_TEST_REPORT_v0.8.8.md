# Acceptance Test Report — v0.8.8

## Scope

Case-insensitive username authentication and uniqueness while preserving entered capitalization.

## Automated results

- Complete application regression suite: **110 passed** across four isolated groups.
- Dedicated v0.8.8 tests: **5 passed**.
- Username capitalization preservation: passed.
- Lower-, upper-, and mixed-case authentication variants: passed.
- Surrounding whitespace normalization: passed.
- Case-only duplicate prevention: passed.
- Password case sensitivity: passed.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- OpenAPI generation/version contract: passed.
- Fresh Alembic migration to `m83j6e2h0f43`: passed.
- Upgrade from v0.8.7 `l72i5d1g9e32`: passed; stored username remained unchanged and normalized key was backfilled.
- Existing case-insensitive collision preflight: passed; migration stopped with an explicit collision error before schema modification.

## Controlled Windows gate

The release installer reruns `Deploy.ps1 -Action Validate -Environment staging -Region ohio`, including the repository-pinned Ruff and mypy checks, before it can create a commit or promote staging. Ruff/mypy executables are not installed in the packaging runtime.
