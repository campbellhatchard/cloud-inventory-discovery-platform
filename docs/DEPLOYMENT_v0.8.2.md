# Deployment Guide — v0.8.2

## Base

The package must be applied to the exact deployed v0.8.1 staging commit:

`c12c6e6321b07483cd0045c414fd4e53c4d8e4fd`

## Feature branch

`feature/usability-media-workflow-v0.8.2`

## Deployment sequence

1. Place the v0.8.2 PowerShell installer and source ZIP in the Windows Downloads folder.
2. Run the installer with `-PromoteToStaging`.
3. The installer verifies the exact v0.8.1 staging commit, applies v0.8.2, and runs complete staging validation.
4. It commits and pushes only after validation passes.
5. In Render, run Sync Blueprint.
6. Deploy the Web service first so Alembic adds the Branding photo-size fields.
7. Confirm the Web deployment succeeds.
8. Deploy the Worker for application-version parity.

## Configuration impact

No new environment variables are required. Do not alter existing PostgreSQL, Cloudflare R2, OpenAI, AI-policy, or LibreOffice settings.

## Staging smoke test

1. Confirm navigation order: Overview, Report, Demo Preparation.
2. In Administration > Branding, save centimetre and inch photograph dimensions.
3. In Administration > Capabilities and Knowledge, complete an approval and confirm the active tab remains selected.
4. Upload a prospect logo and confirm it appears in the report header.
5. Upload two photographs to Receiving and confirm visible thumbnails.
6. Open a photograph and confirm it previews in a modal.
7. Select both photographs and move them to Picking.
8. Delete one photograph and confirm it is removed.
9. Confirm the page remains at Site Photographs and Attachments after media actions.
10. Open Overview and verify the readiness table fits the desktop page.
11. Open Report and confirm Generated Documents is under Report Review and shows only the latest item for each document type.
12. Generate a draft report and confirm photograph dimensions and prospect cover logo.
