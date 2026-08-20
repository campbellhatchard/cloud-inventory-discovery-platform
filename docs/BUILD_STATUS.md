# Build Status

## Current feature build

- Version: **0.8.11**
- Build date: **13 August 2026**
- Status: **Implemented and automated validation passed; awaiting controlled Windows staging validation and deployment**
- Intended feature branch: `feature/section-page-simplification-v0.8.11`
- Locked source baseline: **v0.8.10**, exact staging commit `999e6c870d54fad1ea872c4959f0433abeae8796`
- Baseline / migration head: `n94k7f3i1g54`
- Enhancement specification: [`SECTION_PAGE_SIMPLIFICATION_SPEC_v0.8.11.md`](SECTION_PAGE_SIMPLIFICATION_SPEC_v0.8.11.md)

## v0.8.11 implemented scope

| Area | Status |
| --- | --- |
| Discovery Questions hidden by default | Implemented |
| Discovery Questions reveal as question-only read-only list | Implemented |
| Per-question answer/photo-entry controls removed | Implemented |
| Discovery Questions reset closed after report-screen navigation | Implemented |
| Section Demo Priority UI and collection removed | Implemented |
| Legacy Demo Priority values excluded from active AI demo-plan input/readiness | Implemented |
| Approved functionality mapping display removed from section page | Implemented |
| Underlying governed mappings retained | Confirmed |
| AI Assistance inspector removed | Implemented |
| On-demand AI History added with status, generated content, and eligible review actions | Implemented |
| AI History reset closed after report-screen navigation | Implemented |
| No schema migration or new Render setting | Confirmed |

## Quality gates completed

- Automated test suite: **126 passed** (53 + 24 + 49 isolated groups)
- Dedicated v0.8.11 tests: **6 passed**
- Python module compilation: pass
- JavaScript syntax validation: pass
- Alembic head remains `n94k7f3i1g54`; no database change required

## Remaining controlled deployment gates

1. Run Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio`; this includes pinned Ruff and mypy checks unavailable in the packaging runtime.
2. Deploy Web and confirm Discovery Questions and AI History are initially closed on Receiving, Putaway, Picking, and other operational sections.
3. Confirm moving to another section and returning resets both optional panels to closed.
4. Confirm Demo Priority and mapping-display sections are absent while Cloud Inventory mapping and AI/report logic remain functional.
5. Deploy Worker after Web is healthy.
