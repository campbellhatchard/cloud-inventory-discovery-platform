# Deployment Guide — v0.8.10

## Locked baseline
- Baseline version: `0.8.9`
- Exact staging SHA: `3ec9ef88c670cddb67e75d13f804e97e75483290`
- Alembic head remains: `n94k7f3i1g54`
- Feature branch: `feature/ai-enhancement-status-v0.8.10`

## Deployment
1. Place the v0.8.10 implementation ZIP and PowerShell installer directly in Downloads. Do not extract the ZIP.
2. Run the installer with `-PromoteToStaging`.
3. The installer verifies the exact v0.8.9 staging SHA, applies v0.8.10, runs the complete Windows validation gate, commits, pushes the feature branch, and fast-forwards staging only after validation passes.
4. Deploy Render Web. No database migration beyond the existing `n94k7f3i1g54` head is required.
5. Confirm `/readyz` is healthy and application version is 0.8.10.
6. Confirm a section with no AI history shows `Status: Not Run`; generate AI wording and confirm `Status: Not Reviewed`; accept it and confirm `Status: Accepted`.
7. Deploy Worker after Web is healthy.

No new Render environment variables are required.
