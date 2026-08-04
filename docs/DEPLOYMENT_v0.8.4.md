# Deployment Guide — v0.8.4

## Baseline

Apply this package only to a clean repository whose application identifies as **v0.8.3** and contains Alembic revision `h38e1f7c5a88`.

The PowerShell installer resolves the current `origin/staging` commit dynamically because the v0.8.3 commit is created by the prior deployment workflow. An optional `-ExpectedBaseSha` parameter can pin the exact commit when known.

## Feature branch

`feature/durable-ai-wording-v0.8.4`

## Deployment sequence

1. Download the v0.8.4 implementation package or source ZIP and installer to the Windows Downloads folder.
2. Ensure the local repository is clean.
3. Run the installer, optionally with `-PromoteToStaging`.
4. The installer verifies application version v0.8.3 and migration `h38e1f7c5a88`, applies the source, and runs `Deploy.ps1 -Action Validate -Environment staging -Region ohio`.
5. The installer commits and pushes only after validation succeeds.
6. In Render, run **Sync Blueprint**.
7. Deploy **Web first** so Alembic adds AI wording fingerprint and lineage columns.
8. Confirm Web deployment succeeds.
9. Deploy **Worker**.

## Configuration impact

No new environment variables are required. Existing PostgreSQL, Cloudflare R2, OpenAI, Zero Data Retention, and LibreOffice settings remain in effect.

## Staging smoke test

1. Enter Current Operations notes in an operational section.
2. Select **AI Enhance** and allow a draft to appear.
3. Close the AI window without accepting the wording.
4. Reopen the report and AI Wording; confirm the same suggestion ID and wording are restored and no new AI job is created.
5. Log in from another browser or device and confirm the same behavior.
6. Select **Refine**, enter a clear instruction, and confirm a child suggestion is created while the original remains in history.
7. Confirm the child lineage includes the parent ID, base wording, and refinement instruction.
8. Change the Current Operations narrative or another written source.
9. Reopen AI Wording and confirm the prior wording is shown as stale and cannot be accepted or refined.
10. Select **Generate updated wording** and confirm the stale suggestion remains in history.
11. Without changing sources, select **Generate another version** and confirm a new job is created only because the user explicitly requested it.
12. Accept verified wording and confirm the original Current Operations wording remains in section version history.
13. Confirm independent photo analysis and report publication still operate normally.
