# PowerShell Deployment Toolkit

## Purpose

`Deploy.ps1` is the supported deployment entry point for the Cloud Inventory Site Discovery Platform. It is staging-first and can:

- generate an environment-specific `render.yaml` from `render.template.yaml`;
- scan the repository for supplied secrets and the prohibited bootstrap password literal;
- validate the application in a temporary copy before changing Git history;
- run Ruff, Pytest, Python compilation, and an optional Docker build;
- validate the Render Blueprint when the Render CLI or Render API is available;
- initialize or publish a GitHub repository without force-pushing;
- open the initial Render Blueprint approval flow;
- apply service secrets through the Render API;
- deploy the web service first, wait for migrations and health, then deploy the worker;
- enforce a separate production confirmation gate.

The generated Blueprint sets `autoDeployTrigger: off`. This prevents Render from racing the scripted secret update, migration, health, and worker gates after a Git push.

## Prerequisites

Install these tools on the Windows workstation used for deployment:

1. PowerShell 7 (recommended) or Windows PowerShell 5.1.
2. Git for Windows.
3. Python 3.12 or 3.13.
4. GitHub CLI (`gh`) when the script must create the repository.
5. Docker Desktop only when using `-BuildDockerImage`.
6. Render CLI is optional. Without it, Blueprint validation uses the Render API when credentials are present, otherwise Render validates during the browser approval flow.

Authenticate GitHub before publishing:

```powershell
gh auth login
gh auth status
```

## Prepare staging secrets

Copy the example file. The copied file is ignored by Git.

```powershell
Copy-Item .\deploy.secrets.example.env .\deploy.secrets.staging.env
notepad .\deploy.secrets.staging.env
```

Required staging values:

```dotenv
BOOTSTRAP_ADMIN_EMAIL=admin@your-company.com
BOOTSTRAP_ADMIN_PASSWORD=<unique-staging-password-or-leave-blank-for-interactive-generation>

S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
S3_BUCKET=<private-staging-bucket>
S3_REGION=auto
S3_ACCESS_KEY_ID=<scoped-access-key>
S3_SECRET_ACCESS_KEY=<scoped-secret-key>

OPENAI_API_KEY=
OPENAI_PROJECT_ID=
AI_ENABLED=false
AI_CONFIDENTIAL_CONTENT_ENABLED=false
OPENAI_DATA_CONTROL_MODE=standard-disabled-for-confidential
```

Use a dedicated staging bucket and credentials. Do not share the production database, bucket, access keys, bootstrap password, or OpenAI project with staging.

## Optional Render API configuration

A Render API key enables service discovery, secret updates, deployment polling, and health verification after the Blueprint resources exist.

Set these only in the current PowerShell process or a secure user-level secret store:

```powershell
$env:RENDER_API_KEY = '<Render API key>'
$env:RENDER_WORKSPACE_ID = '<Render workspace ID, usually tea-...>'
```

Existing service IDs can be supplied explicitly, but the script normally discovers them by the generated staging or production names:

```powershell
$env:RENDER_WEB_SERVICE_ID = 'srv-...'
$env:RENDER_WORKER_SERVICE_ID = 'srv-...'
```

Never place the Render API key in a repository file.

## Validate before publishing

Run the complete staging validation gate:

```powershell
.\Deploy.ps1 `
  -Action Validate `
  -Environment staging `
  -Region ohio
```

Add a local Docker build when Docker Desktop is available:

```powershell
.\Deploy.ps1 `
  -Action Validate `
  -Environment staging `
  -Region ohio `
  -BuildDockerImage
```

The validation runs in a temporary copy. It does not create a Git commit, push to GitHub, or modify Render.

## Publish and start the initial staging deployment

```powershell
.\Deploy.ps1 `
  -Action Deploy `
  -Environment staging `
  -GitHubOwner '<github-user-or-organization>' `
  -RepositoryName 'cloud-inventory-discovery-platform' `
  -RepositoryVisibility private `
  -SecretsFile .\deploy.secrets.staging.env `
  -Region ohio
```

By default, staging is published to the `staging` branch. Production is published to `main`. Each environment has a separate Render project, services, database, secrets, and Blueprint connection, so changing the production Blueprint cannot remove or reconfigure staging resources.

The script will:

1. generate the staging Blueprint;
2. validate the exact source in a temporary directory;
3. initialize Git if necessary;
4. create or reuse the GitHub repository;
5. commit and push the validated source;
6. wait for the repository's `CI` GitHub Actions workflow to pass;
7. open Render's Blueprint deployment page.

For a private GitHub repository, authorize Render's GitHub App for that repository. Review the Blueprint plan and provide the values requested for `sync: false` variables using the local ignored handoff file in `deployment-output`.

The initial Blueprint connection is a browser-authorized action. After the resources exist, rerun the toolkit to complete API-driven deployment verification:

```powershell
.\Deploy.ps1 `
  -Action Redeploy `
  -Environment staging `
  -SecretsFile .\deploy.secrets.staging.env
```

When a Render API key is configured, the redeploy action updates secrets, deploys the web service, waits for its pre-deploy migration and `/readyz` check, and only then deploys the worker.

## Non-interactive redeployment

Use this only after the GitHub repository and Render services already exist:

```powershell
$env:RENDER_API_KEY = '<Render API key>'
$env:RENDER_WORKSPACE_ID = '<workspace ID>'
$env:RENDER_WEB_SERVICE_ID = '<staging web service ID>'
$env:RENDER_WORKER_SERVICE_ID = '<staging worker service ID>'

.\Deploy.ps1 `
  -Action Redeploy `
  -Environment staging `
  -SecretsFile .\deploy.secrets.staging.env `
  -NonInteractive
```

All required secrets must be present in the ignored secrets file or process environment for non-interactive use.

## Production deployment gate

Production is blocked unless both the switch and the exact interactive confirmation are supplied. First create a separate secret file and ensure it references production-only storage credentials:

```powershell
Copy-Item .\deploy.secrets.example.env .\deploy.secrets.production.env
notepad .\deploy.secrets.production.env
```

After staging acceptance and backup/restore verification:

```powershell
.\Deploy.ps1 `
  -Action Deploy `
  -Environment production `
  -ConfirmProduction `
  -GitHubOwner '<github-user-or-organization>' `
  -SecretsFile .\deploy.secrets.production.env `
  -Region ohio `
  -ServicePlan starter `
  -DatabasePlan basic-256mb
```

The interactive script then requires the operator to type:

```text
DEPLOY PRODUCTION
```

Production uses the `main` branch, unique project/service/database names, and a protected Render environment. Staging remains linked to the separate `staging` branch.

For a controlled non-interactive production run, both safeguards remain required:

```powershell
$env:PRODUCTION_DEPLOY_CONFIRMATION = 'DEPLOY PRODUCTION'
.\Deploy.ps1 `
  -Action Redeploy `
  -Environment production `
  -ConfirmProduction `
  -NonInteractive `
  -SecretsFile .\deploy.secrets.production.env
```

Do not persist `PRODUCTION_DEPLOY_CONFIRMATION` in the repository or a general-purpose profile.


## Actions and key switches

| Parameter | Purpose |
| --- | --- |
| `-Action Validate` | Generate and validate only; no GitHub or Render changes. |
| `-Action Publish` | Validate, commit, and push; do not change Render. |
| `-Action Deploy` | Publish and start or complete deployment. |
| `-Action Redeploy` | Publish current changes and redeploy existing services. |
| `-Environment staging` | Default and recommended proving environment. |
| `-Environment production` | Production resource names and protected environment. |
| `-BuildDockerImage` | Add a local Docker image build to validation. |
| `-ClearBuildCache` | Ask Render to clear service build cache for API-triggered deploys. |
| `-SkipTests` | Bypass local tests; not appropriate for production release. |
| `-SkipGitHubPush` | Do not push; Render deploys the latest commit already on its linked branch. |
| `-SkipGitHubChecks` | Explicitly bypass waiting for the remote `CI` workflow; production use requires a conscious override. |
| `-DryRun` | Show external commands and create only an ignored generated Blueprint. |
| `-KeepSecretHandoff` | Retain the local secret handoff after a verified API deployment. |
| `-NoBrowser` | Print the Blueprint URL without opening it. |
| `-GitAuthorName` / `-GitAuthorEmail` | Supply a local Git commit identity when Git has not been configured. |
| `-DatabaseDiskSizeGB` | Render Postgres disk size; must be 1 GB or a multiple of 5 GB. |
| `-GitHubChecksTimeoutSeconds` | Maximum wait for the GitHub `CI` workflow; default 900 seconds. |

Get complete parameter help:

```powershell
Get-Help .\scripts\Deploy-CloudInventoryDiscovery.ps1 -Detailed
```

## Secret handling

The deployment toolkit does not commit secrets. It writes a temporary handoff file under:

```text
deployment-output/render-secrets.<environment>.env
```

This directory is ignored by Git. On Windows, the script attempts to remove inherited ACLs and grant access only to the current user. When an API-driven deployment completes, the handoff file is removed unless `-KeepSecretHandoff` is supplied. Delete any retained copy after use.

The requested initial administrator username remains `Admin`. The password is supplied only as a deployment secret, is hashed during seed initialization, and must be changed at first login. Optional OpenAI values are applied through the Render API or added later in the Render Dashboard; they are not required for the initial AI-disabled Blueprint.

## Failure handling

The script stops before GitHub publication when tests or source-secret scanning fail. It stops before worker deployment when the web deployment, migration, or readiness check fails. It does not force-push and does not automatically delete existing Render resources.

For a failed web deployment:

1. inspect the Render build and pre-deploy logs;
2. correct the source or environment variables;
3. rerun `-Action Validate`;
4. commit and redeploy staging;
5. do not deploy production until the proving checklist passes.
