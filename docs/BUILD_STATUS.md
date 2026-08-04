# Build Status

## Current feature build

- Version: **0.8.6**
- Build date: **4 August 2026**
- Status: **Implemented and Linux-side automated validation passed; awaiting controlled Windows staging validation and deployment**
- Intended feature branch: `feature/user-admin-evidence-privacy-speech-v0.8.6`
- Source baseline: application version **v0.8.5**, exact staging commit `a8eea8336863d48e9beb3ed938846965bb942b42`
- Migration head: `k61h4c0f8d21`
- Enhancement specification: [`USER_ADMIN_EVIDENCE_PRIVACY_SPEECH_SPEC_v0.8.6.md`](USER_ADMIN_EVIDENCE_PRIVACY_SPEECH_SPEC_v0.8.6.md)

## v0.8.6 implemented scope

| Area | Status |
| --- | --- |
| Admin reset user password | Implemented |
| Configured temporary password and forced first-login change | Implemented |
| Password minimum reduced to 10 with complexity retained | Implemented |
| Controlled user soft deletion and session/access revocation | Implemented |
| Report/engagement ownership reassignment and prospect access preservation | Implemented |
| Photograph AI interpretation retired end to end | Implemented |
| Photograph capture/upload/caption/publication retained | Implemented |
| Legacy photo-AI cache table removed by migration | Implemented |
| System / Browser Default speech behavior | Implemented |
| Per-device voice selector, rate and Test Voice | Implemented |

## Quality gates completed

- Automated test suite: **99 passed**
- Dedicated v0.8.6 + retained fast-text regression tests: **8 passed**
- Python module compilation: pass
- JavaScript syntax validation: pass
- Fresh Alembic migration to `k61h4c0f8d21`: pass
- Upgrade migration from v0.8.5 `j50g3b9e7c10` to `k61h4c0f8d21`: pass

## Remaining controlled deployment gates

1. Generate and verify OpenAPI and release package.
2. Run Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio`; this includes pinned Ruff and mypy checks unavailable in the packaging runtime.
3. Configure the web-service secret `DEFAULT_USER_TEMP_PASSWORD` with the approved temporary-password value.
4. Deploy Web first so Alembic retires legacy photo-AI cache data, then deploy Worker.
5. Complete staging smoke tests for user reset/delete, evidence upload, text AI, and speech selection.
