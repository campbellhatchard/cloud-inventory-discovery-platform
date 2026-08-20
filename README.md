# Cloud Inventory Site Discovery Platform

Production-oriented internal web application for capturing onsite discovery, collaborating across Sales and Presales, governing Cloud Inventory capability recommendations, and generating controlled customer deliverables in DOCX and PDF.

The canonical product and software requirements are in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md).

## Current release

**Version:** 0.2.0
**Status:** GitHub-ready, Render-ready implementation with a staging-first PowerShell deployment toolkit
**Primary benchmark:** Denver International Airport Site Survey Report structure and branding

## What is implemented

- Responsive mobile, tablet, and desktop single-page interface
- Application-managed authentication using Argon2id password hashing
- First-login password change, secure sessions, CSRF protection, and login lockout
- Contributor, reviewer, owner, and administrator roles
- Prospect-level isolation, report membership, section assignment, comments, and optimistic concurrency
- Multiple reports per prospect and owner-controlled report merge with lineage
- Standard and custom report sections
- Guided questions plus free-form narrative capture
- Quick field capture, browser autosave, and offline-safe IndexedDB queue
- Photograph and attachment upload, image normalization, captions, placement control, and text extraction
- Findings, baseline metrics, approved capability mappings, qualitative and measurable benefits
- Governed capability catalog and human-approved knowledge repository
- Queued AI assistance with policy gating and mandatory human review
- Draft/final validation and publication workflow
- Denver-styled DOCX and PDF generation with configurable branding and draft watermarking
- Full Discovery Report, Solution Demonstration Brief, and Customer Follow-up Questionnaire outputs
- Prospect export, archive workflow, retention review, legal hold, and controlled deletion
- Audit log
- PostgreSQL/Alembic migrations, S3-compatible private object storage, DB-backed worker queue
- GitHub Actions test/lint pipeline, environment-specific Render Blueprint, and PowerShell deployment automation

## Architecture

```text
Browser/PWA
    |
    v
FastAPI Web Service ---- PostgreSQL
    |                        |
    |                        +-- transactional data, audit, queue state
    |
    +---- Private S3-compatible object storage
    |       photos, attachments, DOCX, PDF, exports
    |
    +---- DB-backed worker
            publication generation
            queued AI generation
            retention maintenance
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the detailed component and trust-boundary model.

## Local development

### Prerequisites

- Python 3.12 or 3.13
- LibreOffice Writer for PDF conversion
- Git

On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y libreoffice-writer fonts-liberation
```

### Setup

```bash
git clone <repository-url>
cd cloud-inventory-discovery-platform
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Set a unique local bootstrap password in `.env`; never commit it.

```dotenv
BOOTSTRAP_ADMIN_PASSWORD=<unique-local-secret>
```

Initialize and run:

```bash
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

Run the worker in a second terminal:

```bash
source .venv/bin/activate
python -m app.worker
```

Open `http://localhost:8000`.

### Tests

```bash
make check
```

Or individually:

```bash
ruff check .
pytest -q
python -m compileall app
node --check app/static/app.js
```

## Initial administrator

The bootstrap username defaults to `Admin`. The password must be supplied through the `BOOTSTRAP_ADMIN_PASSWORD` environment secret. The password is hashed on initialization and the administrator must change it at first login.

No real password is stored in this repository.

## Render deployment

The repository contains [`render.yaml`](render.yaml), which provisions:

- one Docker web service;
- one Docker background worker; and
- one Render PostgreSQL database.

The pre-deploy command runs Alembic migrations and idempotent seed loading.

Detailed instructions and required secrets are in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

### PowerShell deployment

From a Windows PowerShell terminal, validate staging before publishing:

```powershell
Copy-Item .\deploy.secrets.example.env .\deploy.secrets.staging.env
notepad .\deploy.secrets.staging.env
.\Deploy.ps1 -Action Validate -Environment staging
```

Publish to GitHub and open the initial Render Blueprint flow:

```powershell
.\Deploy.ps1 `
  -Action Deploy `
  -Environment staging `
  -GitHubOwner '<github-user-or-organization>' `
  -SecretsFile .\deploy.secrets.staging.env
```

The toolkit validates in a temporary copy, prevents supplied secrets from entering Git, publishes staging to the `staging` branch and production to `main`, generates separate Render projects/resources, and deploys the worker only after the web migration and readiness gate. See [`docs/POWERSHELL_DEPLOYMENT.md`](docs/POWERSHELL_DEPLOYMENT.md).

## Object storage

Production is designed for a private S3-compatible bucket such as Cloudflare R2. Objects are partitioned by prospect:

```text
prospects/<prospect-id>/evidence/...
prospects/<prospect-id>/publications/...
prospects/<prospect-id>/exports/...
```

Application authorization is checked before an object is returned. Private objects are never exposed by a public bucket URL.

## AI configuration

AI is disabled by default. Prospect-confidential content is sent only when all of these conditions are true:

```dotenv
AI_ENABLED=true
AI_CONFIDENTIAL_CONTENT_ENABLED=true
OPENAI_DATA_CONTROL_MODE=zero_data_retention
OPENAI_API_KEY=<secret>
OPENAI_MODEL=gpt-5-mini
```

The application uses the Responses API with `store=False`, queues generation in the worker, restricts recommendations to approved capabilities and approved knowledge, and stores all output as a pending suggestion. A reviewer must approve content before it is applied.

Do not enable confidential AI processing until the organization has verified that its OpenAI project is approved for the required data-retention controls. See [`docs/SECURITY.md`](docs/SECURITY.md).

## Supported evidence uploads

- Images supported by Pillow
- PDF
- DOCX
- XLSX
- CSV
- TXT
- Markdown
- JSON
- XML

The application applies file-size limits, extension/content checks, safe filenames, private storage, and structural validation. It does **not** include an antivirus engine in v0.2.0. Deployments that require malware scanning must add an approved scanning service or quarantine gateway before wider production use.

## Repository guide

```text
app/
  api.py                 REST API
  auth.py                authentication and authorization helpers
  ai_service.py          policy, grounding, OpenAI request, AI job execution
  documents.py           DOCX and PDF generation
  extraction.py          supporting-document text extraction
  maintenance.py         retention and merged-report cleanup
  models.py              SQLAlchemy domain model
  publication_service.py publication worker logic
  static/                 responsive PWA frontend
alembic/                  database migrations
assets/                   capability/question seeds and default logo
docs/                     specification and operating documentation
tests/                    security, access, workflow, collaboration tests
render.yaml               Render Blueprint
```

## Known production prerequisites

Before customer-confidential production use, the deploying organization must complete:

1. Security and privacy review of the hosting region, database, object store, and AI project.
2. Backup and restore drill for PostgreSQL and object storage.
3. Approved malware-scanning decision for uploaded attachments.
4. Verification of object-store lifecycle policies against the application retention policy.
5. Final branding/legal-text approval.
6. Product governance approval of the seeded capability catalog.
7. User acceptance testing on target mobile devices and browsers.

## Documentation

- [Complete software specification](docs/SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Render deployment](docs/DEPLOYMENT.md)
- [PowerShell deployment toolkit](docs/POWERSHELL_DEPLOYMENT.md)
- [Security and privacy](docs/SECURITY.md)
- [Operations and retention](docs/OPERATIONS.md)
- [User guide](docs/USER_GUIDE.md)
- [Build status and acceptance evidence](docs/BUILD_STATUS.md)
- [Release notes v0.2.0](docs/RELEASE_NOTES_v0.2.0.md)
- [Generated OpenAPI schema](docs/openapi.json)
