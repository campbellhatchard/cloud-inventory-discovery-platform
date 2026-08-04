# Build Status

## Current feature build

- Version: **0.8.7**
- Build date: **4 August 2026**
- Status: **Implemented and automated validation passed; awaiting controlled Windows staging validation and deployment**
- Intended feature branch: `feature/user-lifecycle-role-admin-v0.8.7`
- Locked source baseline: **v0.8.6**, exact commit `4aaa7369de80e69e9f297c1dbc9be1705eacbfe6`
- Baseline migration: `k61h4c0f8d21`
- Migration head: `l72i5d1g9e32`
- Enhancement specification: [`USER_LIFECYCLE_ROLE_ADMIN_SPEC_v0.8.7.md`](USER_LIFECYCLE_ROLE_ADMIN_SPEC_v0.8.7.md)

## v0.8.7 implemented scope

| Area | Status |
| --- | --- |
| Administrator role editing | Implemented |
| Contributor / Reviewer / Owner / Administrator role combinations | Implemented |
| Delete User retired | Implemented |
| Explicit Active / Inactive lifecycle | Implemented |
| Deactivation revokes active sessions | Implemented |
| Roles and memberships preserved during deactivation | Implemented |
| Reactivation restores login eligibility | Implemented |
| Owner/engagement reassignment required when needed | Implemented |
| Last active Administrator protection | Implemented |
| Self-deactivation protection | Implemented |
| Active users only in collaboration selectors | Implemented |
| Legacy v0.8.6 DELETED rows converted to INACTIVE | Implemented |

## Quality gates completed

- Automated test suite: **105 passed**
- Dedicated v0.8.7 lifecycle/role tests: **6 passed**
- Python module compilation: pass
- JavaScript syntax validation: pass
- OpenAPI generation: pass, version **0.8.7**
- Fresh Alembic migration to `l72i5d1g9e32`: pass
- Upgrade migration from v0.8.6 `k61h4c0f8d21` to `l72i5d1g9e32`: pass
- User-delete API route absent from OpenAPI: pass

## Remaining controlled deployment gates

1. Run Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio`; this includes pinned Ruff and mypy checks unavailable in the packaging runtime.
2. Deploy Web first so migration `l72i5d1g9e32` converts any legacy DELETED user rows to INACTIVE.
3. Confirm role editing, deactivate/reactivate, password reset, and assignment selectors in staging.
4. Deploy Worker after Web is healthy.
