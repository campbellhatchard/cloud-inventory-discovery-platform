# Deployment — v0.7.1

## Base

This hotfix must be applied to the deployed v0.7.0 staging commit:

`05cb6be56772fdaf0db43d4e489cbdada33f2c7f`

The installer creates:

`hotfix/manual-cloud-inventory-approach-v0.7.1`

## Deployment sequence

1. Place the v0.7.1 installer and source ZIP in the Windows Downloads folder.
2. Run the installer with `-PromoteToStaging`.
3. The installer verifies the exact staging commit and a clean local repository.
4. Complete staging validation runs before commit or push.
5. The validated hotfix branch is pushed and staging is fast-forwarded.
6. In Render, run **Sync Blueprint**.
7. Manually deploy the latest staging commit to Web.
8. Manually deploy the latest staging commit to Worker for version parity.

## Environment

No environment variable changes are required. Keep current OpenAI and Cloudflare R2 settings unchanged.

## Smoke test

1. Open an operational section such as Picking.
2. Enter text in **Cloud Inventory approach narrative**.
3. Wait for the status to show **Saved**.
4. Reload the page and confirm the text remains.
5. Open Version history and confirm a USER version exists.
6. Map an approved capability and confirm it remains a separate mapping.
7. Select Enhance with AI and confirm the saved manual text is shown as the current approach context.
8. Generate a draft report and confirm the manual approach appears.
