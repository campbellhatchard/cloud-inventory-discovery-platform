# Staging Deployment — v0.5.0

1. Run `Apply_Report_Review_Usability_v0.5.0_From_Downloads.ps1` from the Windows Downloads folder.
2. The installer stages release files under `CloudInventoryDiscovery\installers\v0.5.0-report-review-usability`.
3. It verifies the locked `baseline-v0.4.1` commit, creates `feature/report-review-usability-v0.5.0`, applies source, runs full staging validation, commits, and pushes the feature branch.
4. Add `-PromoteToStaging` only when the validated feature should be fast-forwarded to `staging` for Render deployment.
5. In Render, Sync Blueprint if APP_VERSION changes are shown, then manually deploy the latest staging commit. Do not deploy this release to production before staging acceptance.
