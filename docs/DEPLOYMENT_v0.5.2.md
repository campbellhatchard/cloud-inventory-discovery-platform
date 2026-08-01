# Deployment Guide - v0.5.2

## Base
- Locked base branch: `baseline-v0.5.1`
- Locked base commit: `3d57b191adf7c1bc2e95f61393a585ab4b564ed6`
- Target feature branch: `feature/report-output-format-v0.5.2`
- Target environment: Render staging only.

## Installer behavior
The v0.5.2 PowerShell installer:
1. moves downloaded release artifacts into the versioned installer folder;
2. verifies the local Git repository is clean;
3. fetches GitHub and confirms `origin/baseline-v0.5.1` exactly matches the locked commit;
4. creates/resets the v0.5.2 feature branch from that baseline;
5. applies the packaged source;
6. discovers Windows LibreOffice when available;
7. runs `Deploy.ps1 -Action Validate -Environment staging -Region ohio`;
8. commits and pushes only after validation passes;
9. optionally fast-forwards the validated feature branch into `staging`.

## Render deployment
After the installer has successfully promoted the feature to `staging`:
- Sync Blueprint if Render indicates the Docker/Blueprint definition needs synchronization. The v0.5.2 Docker image adds `python3-uno`.
- Manual Deploy -> Deploy latest commit for `cloud-inventory-discovery-staging`.
- Manual Deploy -> Deploy latest commit for `cloud-inventory-discovery-staging-worker`.
- Do not replace the existing Cloudflare R2 secret values; the existing validated R2 configuration remains applicable.

## Proving checklist
- Generate/download Draft Word and Draft PDF.
- Confirm the TOC contains populated page references.
- Confirm bullets and numbered items are indented.
- Confirm page 1 has no footer.
- Confirm page 2 onward has the colour Cloud Inventory logo, exact proprietary notice, and page number.
- Generate a controlled Demo Brief to confirm the worker still persists DOCX/PDF to R2.
- Confirm Generated Documents shows revision/date-time and permits dismissal of a failed historical attempt.
