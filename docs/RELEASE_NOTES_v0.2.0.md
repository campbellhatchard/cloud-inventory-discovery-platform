# Release Notes — v0.2.0

## Deployment release

Version 0.2.0 packages the Cloud Inventory Site Discovery Platform with a staging-first GitHub and Render deployment workflow.

### Added

- Root `Deploy.ps1` entry point and full PowerShell deployment toolkit.
- Environment-specific Render Blueprint generation for isolated staging and production projects.
- Separate web service, worker, PostgreSQL database, object-storage credentials, and bootstrap secret per environment.
- Local validation in a temporary workspace before Git commits or remote changes.
- GitHub repository creation/reuse, branch publication, and GitHub Actions CI waiting.
- Render CLI or API Blueprint validation when credentials are available.
- Render API secret updates, deterministic web-first deployment, Alembic/seed gate, readiness polling, and worker deployment.
- Interactive and non-interactive production confirmation gates.
- Draft secret handoff file with Git ignore and Windows ACL hardening.
- Render PostgreSQL disk-size validation.
- Non-root production Docker image and `.dockerignore` hardening.
- Production configuration tests for PostgreSQL, object storage, bootstrap secrets, and confidential AI policy.

### Changed

- Application version advanced to `0.2.0`.
- Render automatic deploys are disabled. The deployment toolkit owns the CI, secret, migration, health, and worker release sequence.
- Staging deploys from the `staging` branch; production deploys from `main`.
- The known example administrator password is prohibited from source and deployment use.
- Worker startup now retries transient database/runtime failures rather than terminating.

### Validation evidence

- 15 automated tests passed.
- Clean Alembic migration and seed loading passed.
- Python compilation, JavaScript syntax, YAML parsing, OpenAPI generation, and secret scanning passed.
- PowerShell structural validation passed; native parser validation is also configured in GitHub Actions.

### Account-dependent acceptance still required

- Push to the intended GitHub repository.
- Authorize the private repository for the Render GitHub App.
- Create private staging object storage and scoped credentials.
- Validate the Blueprint through the target Render workspace.
- Complete the staging proving checklist before production.
