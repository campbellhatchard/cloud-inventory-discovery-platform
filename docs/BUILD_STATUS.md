# Build Status

## Current feature build

- Version: **0.8.5**
- Build date: **4 August 2026**
- Status: **Implemented and automated validation passed; awaiting controlled staging deployment and user acceptance**
- Intended feature branch: `feature/configuration-intelligence-v0.8.5`
- Source baseline: application version **v0.8.4**
- Migration head: `j50g3b9e7c10`
- Enhancement specification: [`CONFIGURATION_INTELLIGENCE_SPEC_v0.8.5.md`](CONFIGURATION_INTELLIGENCE_SPEC_v0.8.5.md)

## v0.8.5 implemented scope

| Area | Status |
| --- | --- |
| Guided Setup configuration knowledge normalized into repository | Implemented — 126 records |
| Configuration sources prevented from becoming discovery prompts | Implemented |
| Concise high-level capability taxonomy additions | Implemented |
| Locations & Zones configuration intelligence | Implemented |
| Configuration-aware Cloud Inventory Approach retrieval | Implemented |
| Customer-facing internal-identifier/setup-action suppression | Implemented |
| Scope-signal handling for non-standard topics | Implemented |
| JSON/ZIP configuration knowledge import | Implemented |
| Configuration source version/provenance metadata | Implemented |
| Fresh and v0.8.4 upgrade migrations | Passed |

## Quality gates completed

- Automated test suite: **99 passed** across four complete groups
- Dedicated v0.8.5 tests: **7 passed**
- Python bytecode compilation: pass
- JavaScript syntax validation: pass
- OpenAPI generation: pass
- Fresh migration to `j50g3b9e7c10`: pass
- Upgrade migration from `i49f2a8d6b99`: pass

## Remaining gates

1. Confirm the exact deployed v0.8.4 staging commit SHA.
2. Build the standard Downloads installer pinned to that exact SHA.
3. Run Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio`.
4. Deploy Web first so Alembic upgrades the schema, then deploy Worker.
5. Complete staging product-SME review of representative Cloud Inventory Approach wording.
