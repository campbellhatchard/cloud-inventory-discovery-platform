# Deployment Guide — v0.8.11

## Baseline

- Source branch: `staging`
- Exact required baseline SHA: `999e6c870d54fad1ea872c4959f0433abeae8796`
- Baseline application version: `0.8.10`
- Alembic head remains: `n94k7f3i1g54`
- Feature branch: `feature/section-page-simplification-v0.8.11`

## Controlled deployment

1. Place the v0.8.11 implementation ZIP and PowerShell installer directly in Downloads. Do not extract the ZIP.
2. Run the installer with `-PromoteToStaging`.
3. The installer verifies the exact v0.8.10 staging SHA, applies v0.8.11, runs the complete Windows validation gate, commits, pushes the feature branch, and fast-forwards staging only after validation passes.
4. Deploy Render Web. There is no database migration and no new environment variable.
5. Confirm application version 0.8.11 and `/readyz` health.
6. Smoke test Receiving → Discovery Questions/AI History → Putaway → back to Receiving; both panels must return closed.
7. Confirm Demo Priority and dedicated mapping-display sections are absent.
8. Deploy Worker after Web is healthy.
