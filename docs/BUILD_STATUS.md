# Build Status

## Current feature build

- Version: **0.8.8**
- Build date: **5 August 2026**
- Status: **Implemented and automated validation passed; awaiting controlled Windows staging validation and deployment**
- Intended feature branch: `feature/case-insensitive-usernames-v0.8.8`
- Locked source baseline: **v0.8.7**, exact staging commit `290c51583c70e6c7005785f3f8968837b7766225`
- Baseline migration: `l72i5d1g9e32`
- Migration head: `m83j6e2h0f43`
- Enhancement specification: [`USERNAME_CASE_INSENSITIVE_AUTH_SPEC_v0.8.8.md`](USERNAME_CASE_INSENSITIVE_AUTH_SPEC_v0.8.8.md)

## v0.8.8 implemented scope

| Area | Status |
| --- | --- |
| Preserve username capitalization exactly as entered | Implemented |
| Case-insensitive username authentication | Implemented |
| Case-insensitive username uniqueness | Implemented |
| Surrounding username whitespace trimmed | Implemented |
| Existing usernames backfilled to normalized lookup keys | Implemented |
| Password authentication remains case-sensitive | Implemented |
| Existing sessions, roles, memberships, and lifecycle behavior preserved | Implemented |
| Migration collision detection before schema change | Implemented |

## Quality gates completed

- Automated test suite: **110 passed**
- Dedicated v0.8.8 username tests: **5 passed**
- Python module compilation: pass
- JavaScript syntax validation: pass
- OpenAPI generation: pass, version **0.8.8**
- Fresh Alembic migration to `m83j6e2h0f43`: pass
- Upgrade migration from v0.8.7 `l72i5d1g9e32` to `m83j6e2h0f43`: pass
- Case-insensitive collision preflight: pass

## Remaining controlled deployment gates

1. Run Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio`; this includes pinned Ruff and mypy checks unavailable in the packaging runtime.
2. Deploy Web first so migration `m83j6e2h0f43` creates and backfills the normalized username key.
3. Confirm an existing user can sign in using upper-, lower-, and mixed-case username variants.
4. Confirm a case-only duplicate username is rejected.
5. Deploy Worker after Web is healthy.
