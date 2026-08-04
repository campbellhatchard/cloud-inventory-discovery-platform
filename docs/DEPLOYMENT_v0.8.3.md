# Deployment Guide — v0.8.3

## Locked base

The package must be applied to the exact locked v0.8.2 baseline:

`baseline-v0.8.2`

`f9ecbc1e01d38423998cf875fb0657901b3d8297`

## Feature branch

`feature/fast-ai-photo-intelligence-v0.8.3`

## Deployment sequence

1. Place the v0.8.3 PowerShell installer and source ZIP in the Windows Downloads folder.
2. Run the installer with `-PromoteToStaging`.
3. The installer verifies the exact locked v0.8.2 baseline, creates the v0.8.3 feature branch, applies the package, and runs complete staging validation.
4. It commits and pushes only after validation passes.
5. In Render, run **Sync Blueprint**.
6. Deploy the **Web** service first so Alembic adds the background-job queue fields and indexes.
7. Confirm Web deployment succeeds.
8. Deploy the **Worker** so the new processing lanes start against the upgraded schema.

## Configuration impact

No new environment variables are required. Retain existing PostgreSQL, Cloudflare R2, OpenAI, Zero Data Retention, and LibreOffice configuration.

## Staging smoke test

1. Open an operational section containing written Current Operations and no photos.
2. Select **AI Enhance** and confirm the initial wording draft appears before source verification completes.
3. Confirm **Accept enhanced text** is disabled while the status is `VERIFYING SOURCES` and enabled only after verification passes.
4. Confirm the AI wording window no longer reports a fixed browser timeout when a worker job takes longer.
5. Upload at least two section photographs.
6. In **AI Photo Analysis**, select the photographs and choose **Analyze selected photos**.
7. Confirm each photograph independently displays visible observations, cautious interpretations, and uncertainties.
8. Re-run analysis on an unchanged completed photograph and confirm it is returned as cached without waiting for a new visual call.
9. Select analyzed photographs and choose **Compare to Current Operations**.
10. Confirm the comparison distinguishes supported content, added context, potential conflicts, and open questions.
11. Confirm the suggested revision does not cause the original image files to be analyzed again.
12. Apply a verified photo-context revision and confirm the prior Current Operations wording remains in version history.
13. In Administration > Operations, confirm the Worker heartbeat reports v0.8.3 and its lane list.
14. Generate a draft report to confirm publication processing remains operational.
