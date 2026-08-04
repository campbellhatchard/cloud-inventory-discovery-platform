# Acceptance Test Report — v0.8.3

## Automated validation

- Full pytest suite: **87 passed**.
- Dedicated v0.8.3 fast-AI/photo-intelligence tests: **8 passed**.
- Updated v0.6 observation-enhancement regression suite: passed.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- Fresh Alembic migration from initial schema to `h38e1f7c5a88`: passed.
- Upgrade migration from v0.8.2 revision `g27d0e6b4f77` to v0.8.3: passed.
- OpenAPI regenerated as application version 0.8.3 and includes the photo-analysis endpoint.

## Functional acceptance coverage

- Current Operations wording requests are text-only and reject supplied photograph IDs.
- Text wording requests are queued on `FAST_TEXT` with higher interactive priority.
- A generated wording draft is committed with AI job status `VERIFYING` before verification finishes.
- Acceptance remains disabled while verification is in progress.
- The browser no longer contains the fixed 90-poll AI enhancement timeout.
- Independent photograph requests are queued on the `PHOTO_ANALYSIS` lane.
- SHA-matched photograph analysis returns `CACHED` without creating another AI job.
- Photo-context snapshots contain stored visual observations and written sources but no raw image/base64 payload.
- Accepted photo-context revisions create a new Current Operations version with source type `AI_PHOTO_CONTEXT`.
- Queue claiming respects queue lane and numerical priority.
- Worker source includes dedicated fast-text, photo-analysis, general-AI, and publication lanes.

## Packaging-runtime limitation

Ruff is not installed in the packaging runtime. The Windows installer therefore remains responsible for running the repository's complete `Deploy.ps1 -Action Validate` gate, including the pinned Ruff and mypy validation, before any commit or push.
