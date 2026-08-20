# Deployment Guide - v0.7.0

## Baseline

- Locked baseline branch: `baseline-v0.6.1`
- Locked baseline commit: `5089c8ae86abc2253e30a2839c0d9133d7b10847`
- Feature branch: `feature/cloud-inventory-solution-intelligence-v0.7.0`

## Deployment sequence

1. Place the v0.7.0 installer and source ZIP in the Windows Downloads folder.
2. Run `Apply_Cloud_Inventory_Solution_Intelligence_v0.7.0_From_Downloads.ps1 -PromoteToStaging`.
3. The installer verifies the exact locked v0.6.1 baseline before applying source.
4. The installer runs the complete staging validation before any Git commit or push.
5. On success it pushes the feature branch and fast-forwards `staging` when `-PromoteToStaging` is supplied.
6. In Render, Sync Blueprint so both services report `APP_VERSION=0.7.0`.
7. Manually deploy the latest staging commit to both the web service and worker.
8. Do not change existing R2 or OpenAI values unless there is a separate configuration issue.

## Database

The web pre-deploy command runs Alembic. Migration `d94a7b3e1c44` extends capability mappings so they can retain the operational source used for a mapping.

Existing finding-based mappings are preserved and backfilled. No manual SQL is required.

## AI readiness

Before testing Generate with AI, confirm:

- AI status is allowed;
- relevant Cloud Inventory capabilities are `APPROVED` in Administration;
- historical knowledge, if used, has been reviewed and set to `APPROVED`;
- the worker is deployed and running with the same AI/R2 environment values as the web service.

A section with operational notes but no approved capability relevant to its process module will correctly refuse solution generation rather than invent functionality.

## Recommended smoke test

1. Open an operational section such as Picking.
2. Enter a neutral general note in Current Operations without adding it as a formal Finding.
3. Confirm the Findings area identifies general notes as Observations for mapping.
4. Approve or confirm at least one relevant Cloud Inventory capability.
5. Select **Generate with AI** in Cloud Inventory Approach.
6. Confirm the proposal maps functionality back to the general Observation source.
7. Refine the wording using a natural-language instruction.
8. Accept the verified solution.
9. Confirm the accepted text and approved mapping appear in Report Review and draft DOCX/PDF.
