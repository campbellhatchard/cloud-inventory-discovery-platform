# Deployment Package Validation — v0.8.9

## Baseline lock

- Required staging version: **0.8.8**
- Required staging commit: `5e1a7da75d5c3b0b9128ded67ee4c86ce02deaac`
- Required baseline migration: `m83j6e2h0f43`
- Release migration: `n94k7f3i1g54`

## Source validation

- Full application regression: **115/115 passed** across isolated groups of 33 + 18 + 35 + 29.
- Dedicated v0.8.9 unified-current-operations tests: **5 passed**.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- OpenAPI generation: passed at **0.8.9**.
- Fresh Alembic migration to `n94k7f3i1g54`: passed.
- Upgrade from v0.8.8 `m83j6e2h0f43` to `n94k7f3i1g54`: passed.
- Existing narrative + typed Finding data-conversion test: passed.
- Changed Python source unused-import scan: passed.

## Behavioral package checks

- Current Operations Narrative is the only user-facing freeform operational-note surface.
- Quick Entry appends the selected classification as a narrative heading.
- Separate Findings card / Add Finding controls are absent from active frontend source.
- Generated reports do not output a duplicate Current-State Findings block.
- Internal narrative-derived Finding records remain available for classification-aware AI, readiness, mappings, and audit traceability.
- Superseded derived wording marks attached active mappings `STALE`.
- AI observation wording instructions preserve user-selected classification headings.

## Windows deployment gate

The supplied installer performs exact-SHA baseline verification and invokes:

`Deploy.ps1 -Action Validate -Environment staging -Region ohio`

before any commit or push. That Windows gate remains authoritative for Ruff, mypy, PowerShell, and platform-specific document-generation validation.
