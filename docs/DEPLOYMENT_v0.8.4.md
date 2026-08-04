# Deployment Guide - v0.8.4

## Locked staging baseline

- Repository: `campbellhatchard/cloud-inventory-discovery-platform`
- Base branch: `staging`
- Exact verified v0.8.3 commit: `288cc4b1ad1d089e893ac5e1c0db332e896dd6a0`
- Required base application version: `0.8.3`
- Required base Alembic revision: `h38e1f7c5a88`
- Target feature branch: `feature/durable-ai-wording-v0.8.4`

The installer refuses to apply the package if `origin/staging` is not exactly the commit above. This is intentional and prevents an enhancement from being applied to an unknown or later baseline.

## Files to download

Place these two files directly in the Windows Downloads folder:

1. `Apply_Durable_AI_Wording_v0.8.4_From_Downloads.ps1`
2. `Cloud_Inventory_Discovery_Platform_v0.8.4_Implementation_Package.zip`

The installer can also use the standalone source ZIP, but the implementation package is the preferred download because it contains the source, checksum manifest, release notes, specification, acceptance report, and deployment guide.

## Run from PowerShell

Open a normal Windows PowerShell window. The current directory may remain `C:\Windows\System32`; the installer uses absolute paths and does not deploy into the current directory.

Run both commands in the same PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

& "$env:USERPROFILE\Downloads\Apply_Durable_AI_Wording_v0.8.4_From_Downloads.ps1" `
    -PromoteToStaging
```

The execution-policy change applies only to that PowerShell process. It does not change the permanent machine or user policy.

## Installer behavior

The installer follows the established Discovery Reports deployment workflow:

1. Resolves Downloads, the local repository, and installer archive beneath `%USERPROFILE%`.
2. Moves v0.8.4 release artifacts from Downloads into `CloudInventoryDiscovery\installers\v0.8.4-durable-ai-wording`.
3. Handles browser duplicate suffixes such as `(1)`.
4. Extracts the implementation package when the standalone source ZIP is not present.
5. Verifies the source ZIP SHA-256 against the included manifest.
6. Refuses a dirty local Git repository.
7. Fetches GitHub and verifies the exact deployed v0.8.3 staging commit, application version, and migration.
8. Creates or resets `feature/durable-ai-wording-v0.8.4` from the verified staging commit.
9. Applies the source while excluding `.git`, virtual environments, caches, local runtime data, `.env`, deployment secrets, and local databases.
10. Locates LibreOffice and runs:

```powershell
.\Deploy.ps1 -Action Validate -Environment staging -Region ohio
```

11. Commits and pushes the feature branch only after validation succeeds.
12. With `-PromoteToStaging`, pulls `origin/staging`, requires a fast-forward merge, and then pushes staging.

## Render sequence

After the installer succeeds:

1. In Render, run **Sync Blueprint**.
2. Deploy the **Web** service first so Alembic applies revision `i49f2a8d6b99`.
3. Confirm the Web deployment succeeds.
4. Deploy the **Worker** service.
5. Confirm both services report application version `0.8.4`.

No new environment variables are required. Retain the existing PostgreSQL, Cloudflare R2, OpenAI, Zero Data Retention, and LibreOffice settings.

## Staging smoke test

1. Generate Current Operations AI wording and close the window without accepting it.
2. Reopen the report and confirm the same suggestion is restored without a new AI job.
3. Refine the wording and confirm the child suggestion retains parent lineage and the exact refinement instruction.
4. Change a written source and confirm the prior wording becomes stale and cannot be accepted or refined.
5. Explicitly generate updated wording and confirm the stale version remains in history.
6. Confirm photo intelligence and report publication remain operational.
