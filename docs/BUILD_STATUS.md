# Build Status

## Current feature build

- Version: **0.8.4**
- Build date: **4 August 2026**
- Status: **Implemented and automated validation passed; awaiting Render staging deployment and user acceptance**
- Feature branch: `feature/durable-ai-wording-v0.8.4`
- Source baseline: application version v0.8.3
- Migration head: `i49f2a8d6b99`
- Enhancement specification: [`AI_WORDING_PERSISTENCE_SPEC_v0.8.4.md`](AI_WORDING_PERSISTENCE_SPEC_v0.8.4.md)

## v0.8.4 implemented scope

| Area | Status |
| --- | --- |
| Pending AI wording stored before verification completes | Implemented |
| Stable written-source SHA-256 fingerprint | Implemented |
| Restore unchanged unaccepted wording across sessions/devices | Implemented |
| API-level duplicate request prevention | Implemented |
| Explicit Generate another version override | Implemented |
| Stale-source detection and acceptance/refinement blocking | Implemented |
| Immediate-parent refinement payload | Implemented |
| Parent/child lineage, base text, instruction, and supersession metadata | Implemented |
| Fresh and v0.8.3 upgrade migrations | Passed |

## Quality gates completed

- Automated test suite: **92 passed**
- Dedicated v0.8.4 tests: **5 passed**
- Python bytecode compilation: pass
- JavaScript syntax validation: pass
- OpenAPI generation: pass
- Fresh migration to `i49f2a8d6b99`: pass
- Upgrade migration from `h38e1f7c5a88`: pass

## Remaining gates

1. Apply the package to a clean v0.8.3 repository.
2. Run the Windows `Deploy.ps1 -Action Validate` gate, including Ruff and mypy from the pinned local toolchain.
3. Deploy Web first so Alembic upgrades the schema.
4. Deploy Worker after the Web migration succeeds.
5. Complete the staging smoke test and user acceptance.
