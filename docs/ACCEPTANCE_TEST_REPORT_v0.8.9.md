# Acceptance Test Report — v0.8.9

## Automated validation

- Full regression suite: **115 passed** across isolated groups of 33 + 18 + 35 + 29 tests.
- Dedicated Unified Current Operations tests: **5 passed**.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- Fresh Alembic migration to `n94k7f3i1g54`: passed.
- Upgrade from v0.8.8 `m83j6e2h0f43` to `n94k7f3i1g54`: passed.
- Data migration check with an existing narrative and Pain Point: passed; original narrative retained, typed block appended, source marked `NARRATIVE_DERIVED`.
- OpenAPI generation: passed at application version 0.8.9.

## Functional acceptance covered

- Quick Entry appends typed notes to Current Operations Narrative.
- Quick Entry mutation deduplication remains effective.
- Manual narrative edits regenerate current typed classifications.
- Superseded source wording marks attached mappings STALE.
- Separate Findings display/edit controls are absent.
- AI current-operations instructions preserve user-selected classification headings.
- Publication code contains no duplicate Current-State Findings section.

## Remaining gate

Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio` remains the authoritative pre-push Ruff/mypy/PowerShell validation gate.
