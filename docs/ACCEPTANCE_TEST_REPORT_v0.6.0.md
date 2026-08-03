# Acceptance Test Report - v0.6.0

## Release
Cloud Inventory Site Discovery Platform v0.6.0 — AI Observation Enhancement.

## Package pre-validation
Completed on 2026-08-03 against the v0.5.2 source baseline.

- `pytest -q`: **44 passed**.
- `python -m compileall -q app tests alembic`: passed.
- `node --check app/static/app.js`: passed.
- Clean Alembic migration on SQLite from initial schema through `c83f2a9d6e32`: passed.
- OpenAPI document regenerated with application version `0.6.0` and the observation-enhancement request contract.
- Approximate AST unused-import check on changed Python/test files: passed.
- `render.yaml` and `render.template.yaml`: parsed successfully as YAML; AI variables present on web and worker.

## Functional regression coverage
The automated suite covers existing baseline behavior plus the v0.6.0 contracts for:

- source snapshots for current-operations enhancement;
- strict section scoping of selected evidence;
- acceptance replacing the current narrative rather than appending it;
- preservation of original and accepted content versions;
- rejection of AI text that fails factual-support verification;
- rejection of stale suggestions after a collaborator changes the section;
- specialized worker dispatch for observation enhancement;
- side-by-side comparison, photo selection, refinement and browser text-to-speech frontend controls.

## Deployment-time validation
The container used to build this package does not have Ruff installed and cannot download it from the package index. The Windows release installer therefore runs the repository's complete `Deploy.ps1 -Action Validate -Environment staging -Region ohio` workflow before it commits or pushes any source. A failed Ruff, test, migration, JavaScript, document-generation, or other deployment validation prevents commit/push.

## External integration note
No live OpenAI confidential-data request was executed during package pre-validation because no production/staging OpenAI secret is embedded in the build environment. The release uses the existing policy gate and requires an explicitly approved confidential-processing configuration before AI controls become available. Image analysis also requires working R2 access for the worker, because selected photograph bytes are retrieved from object storage.

## Release decision
**Ready for staging deployment subject to successful Windows `Deploy.ps1` validation and deliberate Render AI configuration.**
