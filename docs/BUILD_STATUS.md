# Build Status

## Current feature build

- Version: **0.8.9**
- Build date: **6 August 2026**
- Status: **Implemented and automated validation passed; awaiting controlled Windows staging validation and deployment**
- Intended feature branch: `feature/unified-current-operations-v0.8.9`
- Locked source baseline: **v0.8.8**, exact staging commit `5e1a7da75d5c3b0b9128ded67ee4c86ce02deaac`
- Baseline migration: `m83j6e2h0f43`
- Migration head: `n94k7f3i1g54`
- Enhancement specification: [`UNIFIED_CURRENT_OPERATIONS_SPEC_v0.8.9.md`](UNIFIED_CURRENT_OPERATIONS_SPEC_v0.8.9.md)

## v0.8.9 implemented scope

| Area | Status |
| --- | --- |
| One user-facing Current Operations Narrative per operational section | Implemented |
| Quick Entry writes directly into the narrative | Implemented |
| Observation/Pain Point/Risk/Gap/Strength/Opportunity subheadings preserved | Implemented |
| Separate Findings card and Add Finding UI retired | Implemented |
| Manual narrative edits resynchronize internal typed classifications | Implemented |
| Changed/removed classifications supersede old internal records | Implemented |
| Mappings tied to superseded wording become STALE | Implemented |
| Existing v0.8.8 findings migrated into the narrative | Implemented |
| AI current-operations rewriting instructed to preserve classifications | Implemented |
| DOCX/report preview no longer duplicate Current-State Findings | Implemented |

## Quality gates completed

- Automated test suite: **115 passed** (33 + 18 + 35 + 29 isolated groups)
- Dedicated v0.8.9 tests: **5 passed**
- Python module compilation: pass
- JavaScript syntax validation: pass
- Fresh Alembic migration to `n94k7f3i1g54`: pass
- Upgrade migration from v0.8.8 `m83j6e2h0f43` to `n94k7f3i1g54`: pass
- Existing narrative + finding migration data check: pass
- OpenAPI generation: pass, version **0.8.9**

## Remaining controlled deployment gates

1. Run Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio`; this includes pinned Ruff and mypy checks unavailable in the packaging runtime.
2. Deploy Web first so migration `n94k7f3i1g54` consolidates existing section findings into Current Operations Narrative.
3. Confirm Quick Entry appends the selected classification into the destination narrative and that the separate Findings panel is absent.
4. Confirm manual edits persist and mapped obsolete wording is surfaced as stale when changed.
5. Deploy Worker after Web is healthy.
