# Render Deployment Guide

## Deployment model

The supplied `render.yaml` is the generated staging Blueprint and defines:

- `cloud-inventory-discovery-staging` — Docker web service;
- `cloud-inventory-discovery-staging-worker` — Docker background worker;
- `cloud-inventory-discovery-staging-db` — PostgreSQL database.

`render.template.yaml` is the source template used by `Deploy.ps1`. Staging is published to the `staging` branch and production to `main`. Each environment receives a separate Render project, web service, worker, database, and secret set. Private network isolation is enabled; the production environment is also protected. Render automatic deploys are disabled; `Deploy.ps1` waits for GitHub CI and then controls the web-migration-worker deployment sequence.

The web pre-deploy command runs:

```bash
alembic upgrade head && python -m app.seed
```

Both steps are designed to be repeatable. Seed loading creates missing controlled templates, prompts, capabilities, knowledge records, branding defaults, roles, and the bootstrap administrator without replacing governed records.


## Automated PowerShell path

The recommended deployment path is the staging-first PowerShell toolkit:

```powershell
Copy-Item .\deploy.secrets.example.env .\deploy.secrets.staging.env
.\Deploy.ps1 -Action Validate -Environment staging
.\Deploy.ps1 -Action Deploy -Environment staging -GitHubOwner '<owner>' -SecretsFile .\deploy.secrets.staging.env
```

The initial Render Blueprint connection is approved in the browser. With a Render API key and workspace ID, the script can then apply secrets, trigger the web deployment, wait for pre-deploy migrations and `/readyz`, and deploy the worker. Complete instructions are in [`POWERSHELL_DEPLOYMENT.md`](POWERSHELL_DEPLOYMENT.md).

## 1. Create the GitHub repository

From the repository root:

```bash
git init
git branch -M main
git add .
git commit -m "Initial Cloud Inventory discovery platform"
git remote add origin <github-repository-url>
git push -u origin main
```

Do not commit `.env`, credentials, local databases, generated reports, or object-store data.

## 2. Create private object storage

Provision a private S3-compatible bucket. Cloudflare R2 is the reference option, but AWS S3 or another compatible service may be used.

Create a scoped access key that can read, write, and delete objects only in the designated bucket. Do not enable public access.

Required values:

```text
S3_ENDPOINT
S3_REGION
S3_BUCKET
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
```

For R2, the endpoint normally follows the account-specific R2 S3 endpoint and the region is `auto`.

## 3. Create the Render Blueprint

In Render:

1. Create a new Blueprint.
2. Connect the GitHub repository.
3. Select the branch intended for the environment.
4. Review the resources from `render.yaml`.
5. Enter all values marked `sync: false`.

## 4. Required environment secrets

### Web and worker

```dotenv
S3_ENDPOINT=<private-object-store-endpoint>
S3_REGION=<region-or-auto>
S3_BUCKET=<bucket>
S3_ACCESS_KEY_ID=<secret>
S3_SECRET_ACCESS_KEY=<secret>
```

### Web only

`APP_BASE_URL` is populated from Render's assigned `RENDER_EXTERNAL_URL` by the Blueprint. The worker does not receive the bootstrap password.

```dotenv
BOOTSTRAP_ADMIN_EMAIL=<internal-admin-email>
BOOTSTRAP_ADMIN_PASSWORD=<unique-high-entropy-secret>
```

### Optional AI

Leave disabled until privacy approval is complete:

```dotenv
AI_ENABLED=false
AI_CONFIDENTIAL_CONTENT_ENABLED=false
OPENAI_DATA_CONTROL_MODE=standard-disabled-for-confidential
OPENAI_API_KEY=
OPENAI_PROJECT_ID=
OPENAI_MODEL=gpt-5-mini
```

After the organization has verified the required OpenAI project data controls:

```dotenv
AI_ENABLED=true
AI_CONFIDENTIAL_CONTENT_ENABLED=true
OPENAI_DATA_CONTROL_MODE=zero_data_retention
OPENAI_API_KEY=<secret>
OPENAI_PROJECT_ID=<project-id-if-used>
```

The application blocks confidential AI requests unless all policy settings pass.

## 5. First deployment verification

Verify the following in order:

1. `GET /healthz` returns `status: ok`.
2. `GET /readyz` returns `status: ready`.
3. The pre-deploy migration and seed commands completed successfully.
4. Login with the bootstrap administrator succeeds.
5. The first-login password change is enforced.
6. Create a test prospect and draft report.
7. Upload a test image and supporting TXT/PDF/DOCX file.
8. Generate a draft DOCX and PDF.
9. Download both files and confirm the watermark and branding.
10. Confirm the worker processed the publication job.
11. Confirm private objects cannot be retrieved without application authorization.

## 6. Staging and production

Use separate Render Blueprints/resources or separate environment groups for staging and production. Never point a staging web or worker service at the production database or bucket.

Recommended naming:

```text
cloud-inventory-discovery-staging
cloud-inventory-discovery-staging-worker
cloud-inventory-discovery-staging-db

cloud-inventory-discovery-production
cloud-inventory-discovery-production-worker
cloud-inventory-discovery-production-db
```

Use distinct:

- database;
- object-storage bucket or at minimum isolated bucket prefix and credentials;
- bootstrap password;
- OpenAI project/key;
- application base URL.

## 7. Database migrations

Render runs migrations before a deployment becomes active. For emergency manual execution:

```bash
alembic current
alembic upgrade head
```

Do not use `Base.metadata.create_all()` as the production migration method.

Before a destructive future migration:

1. create a database backup;
2. test upgrade and rollback against a restored staging copy;
3. verify document generation and export;
4. schedule a maintenance window if required.

## 8. Worker monitoring

A healthy web service does not prove the worker is processing jobs. Monitor:

- worker logs;
- queued/running/failed job counts in PostgreSQL;
- publication status and errors;
- AI job status and errors;
- age of the oldest queued job;
- retention maintenance log output.

## 9. Storage lifecycle

Application retention is prospect-aware and must remain authoritative. Do not configure a bucket lifecycle rule that deletes active objects earlier than the application retention period.

A safe approach is:

- no automatic deletion for the active `prospects/` prefix during initial production;
- database-driven archive/export/delete;
- separate lifecycle rules only for abandoned multipart uploads and documented temporary prefixes;
- periodic reconciliation between `file_objects` and bucket keys.

## 10. Rollback

For an application-only regression:

1. roll back to the previous Git commit/deploy;
2. do not downgrade the database unless the migration was explicitly proven reversible;
3. pause the worker if the old code cannot understand the new schema;
4. restore from backup only when data/schema recovery is required.

## 11. Production sign-off checklist

- [ ] Render services and database are in approved regions/plans.
- [ ] TLS and custom domain are configured.
- [ ] Unique bootstrap secret configured and changed after first login.
- [ ] Private object storage and scoped credentials verified.
- [ ] Database backup and restore drill completed.
- [ ] Object export and archive/delete tested.
- [ ] Malware-scanning decision approved.
- [ ] AI remains disabled or approved ZDR configuration verified.
- [ ] Capability catalog reviewed by product governance.
- [ ] Branding, confidentiality text, and logos approved.
- [ ] Mobile/tablet/desktop acceptance testing completed.
- [ ] Draft and final report regression samples approved.
