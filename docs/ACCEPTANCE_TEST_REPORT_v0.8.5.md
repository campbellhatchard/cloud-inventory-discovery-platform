# Acceptance Test Report — v0.8.5

## Automated results

- Total automated tests: **99 passed** in four complete regression groups.
- Dedicated Configuration Intelligence tests: **7 passed**.
- Python compilation: **passed**.
- JavaScript syntax validation: **passed**.
- OpenAPI generation: **passed**, application version 0.8.5 and configuration-import route present.
- Alembic fresh migration: **passed** to `j50g3b9e7c10`.
- Alembic upgrade from v0.8.4 revision `i49f2a8d6b99`: **passed**.
- Ruff: the first Windows deployment validation identified one F401 unused test import; corrected R1 removes that import. The corrected Windows deployment validation remains the final release gate.
- mypy: not available in the current Linux packaging runtime; the Windows deployment validation remains the release gate.

## Dedicated acceptance coverage

1. The controlled seed contains exactly 126 configuration records, effective source version 2.7 and corroborating source version 2.6.
2. Every controlled configuration record is marked never to be used as a discovery prompt.
3. The ten Locations & Zones records preserve location types, zones, capacity and specialist-storage knowledge and map to the concise `CAP-LOC-001` capability.
4. New high-level capabilities remain concise and do not expose `nsC7` or PS implementation terminology.
5. Seeded configuration records exist as repository knowledge while Guided Setup IDs create zero `PromptDefinition` records.
6. A customer observation describing missing location identification/zoning and storage constraints retrieves relevant Location & Zone configuration knowledge.
7. JSON configuration imports create pending knowledge and zero discovery prompts.
8. ZIP import selects the highest Guided Setup template version rather than interpreting bundled HTML applications.
9. AI-generation instructions explicitly prevent configuration-question leakage and require concise high-level capability wording.
10. Cross-dock remains a scope signal and is not represented as an approved standard capability.

## Remaining staging acceptance

- Confirm Administration renders the 126 controlled configuration records and new high-level capabilities correctly.
- Generate a Cloud Inventory Approach from a realistic location/zoning observation and review product wording with a Cloud Inventory product SME.
- Confirm Render Web migration completes before Worker deployment.
- Run the standard Windows `Deploy.ps1 -Action Validate -Environment staging -Region ohio` gate before commit/push.

## Corrected packaging revision R1

The initial v0.8.5 deployment package was stopped by the Windows Ruff gate because `Capability` was imported but unused in `tests/test_configuration_intelligence_v085.py`. No commit or staging promotion occurred. Corrected R1 removes only that unused import, retains the same application version and migration, and adds recovery-aware installer behavior for the known failed-validation state. The full Python suite passes 99 tests after the correction.
