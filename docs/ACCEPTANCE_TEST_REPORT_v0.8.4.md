# Acceptance Test Report — v0.8.4

## Automated validation

- Full pytest suite: **92 passed**.
- Dedicated v0.8.4 durable-wording tests: **5 passed**.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- OpenAPI generation: passed as application version **0.8.4**.
- Fresh Alembic migration to `i49f2a8d6b99`: passed.
- Upgrade migration from v0.8.3 revision `h38e1f7c5a88`: passed.

## Functional acceptance coverage

- Duplicate initial wording requests for unchanged sources return the same AI job.
- A pending suggestion created two days earlier is restored without a new job.
- The current-wording endpoint returns matching persisted wording and lineage metadata.
- Changed written sources classify the prior candidate as stale for UI purposes and block refinement and acceptance.
- Explicit `force_regenerate` creates a new job even when the fingerprint is unchanged.
- Refinement sends the immediate prior enhanced wording, not an earlier ancestor version.
- Refinement sends the exact user instruction and current source evidence.
- Child suggestions persist parent ID, immutable base text, refinement instruction, and source fingerprint.
- Persisting a child marks its parent `SUPERSEDED` and records `superseded_by_suggestion_id`.
- Existing v0.8.3 fast-text and photo-intelligence regression suites continue to pass.

## Packaging-runtime limitation

Ruff and mypy are not installed in the packaging runtime. The Windows installer remains responsible for running the repository's complete pinned `Deploy.ps1 -Action Validate` gate before any commit or push.
