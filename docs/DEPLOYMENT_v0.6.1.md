# Deployment Guide - v0.6.1

## Base

- Exact deployed staging base: `9fa87d0ae43bd56934d09fd40bd3a829c6697d22`
- Feature branch: `hotfix/section-photo-upload-v0.6.1`
- No database migration is introduced.

## Deployment

Run the supplied PowerShell installer from Downloads. The installer verifies the exact v0.6.0 staging commit, applies the source to a dedicated hotfix branch, runs full staging validation, commits and pushes only after validation succeeds, and can fast-forward staging when `-PromoteToStaging` is supplied.

After staging is pushed, manually deploy the latest staging commit to the Render web service. The worker contains the same version metadata but no worker behavior is changed by this hotfix; deploying the worker too keeps both components on the same release version.

No Cloudflare R2 or OpenAI environment changes are required.

## Smoke test

1. Open an active report and select an operational section.
2. Select **Add photographs**.
3. Upload a site photograph with an optional caption.
4. Confirm the photograph appears in the current section without navigating through Quick Entry.
5. Open **AI Enhance** and confirm the photograph is available for selection.
6. Confirm Quick Entry photo/file capture still operates normally.
