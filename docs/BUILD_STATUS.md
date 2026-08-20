# Build Status

## Release

- Version: **0.2.0**
- Build date: **31 July 2026**
- Status: **GitHub-ready / Render-ready implementation**
- Canonical requirements: [`SPECIFICATION.md`](SPECIFICATION.md)

## Implemented scope

| Area | Status |
| --- | --- |
| Responsive PWA | Implemented |
| Authentication and roles | Implemented |
| Prospect/report isolation | Implemented and tested |
| Multi-user reports and assignments | Implemented |
| Comments and optimistic concurrency | Implemented and tested |
| Standard process sections/question library | Implemented |
| Mobile quick capture and offline queue | Implemented |
| Photos and supporting attachments | Implemented |
| Attachment extraction | Implemented and tested |
| Findings, metrics, capabilities, benefits | Implemented |
| Capability/knowledge governance | Implemented and tested |
| Report merge and source lineage | Implemented |
| AI policy gate and queued worker | Implemented; real API requires deployment credentials and approval |
| Human review/application of AI output | Implemented and unit tested |
| Draft/final validation | Implemented |
| DOCX and PDF outputs | Implemented and tested |
| Configurable branding and logo | Implemented |
| Export/archive/retention/delete | Implemented and tested |
| Audit log | Implemented |
| Alembic/PostgreSQL/environment-specific Render Blueprint | Implemented |
| PowerShell staging-first deployment toolkit | Implemented |
| CI pipeline | Implemented |

## Automated acceptance evidence

Current local suite:

```text
15 passed
```

Coverage includes:

- authentication security and first-login change;
- authorization and cross-prospect isolation;
- report creation and standard section generation;
- idempotent/offline mutation handling;
- evidence upload and extraction;
- document generation and draft watermark;
- final-publication validation blocking;
- optimistic concurrency;
- assignment and comments;
- capability governance and knowledge promotion;
- export, archive, prospect deletion, and draft-report deletion;
- queued AI-job execution and mandatory pending review state.

## Quality gates

- Python bytecode compilation: pass
- JavaScript syntax check: pass
- Alembic upgrade against a clean database: pass
- Seed loading against migrated schema: pass
- DOCX/PDF generation: pass
- DOCX/PDF page rendering and visual inspection: pass
- Static unused-import check: pass
- Ruff lint: configured in CI; local Ruff executable was unavailable in the build environment
- GitHub Actions workflow: configured
- PowerShell parser gate: configured in CI
- PowerShell deployment toolkit: structural/static review complete and CI parser gate configured; native `pwsh` execution was unavailable in the Linux build container, and live account actions require user credentials

## Deliberate limitations / remaining deployment acceptance

1. No real GitHub remote has been configured or pushed by this build package.
2. No Render account deployment has been performed; account credentials and approved environment secrets are required. The supplied PowerShell toolkit performs those actions from the operator’s workstation.
3. No live OpenAI API call has been made; confidential AI remains disabled by default.
4. No antivirus engine is bundled. File allowlisting and structural validation are implemented, but production malware scanning requires an organizational decision.
5. PostgreSQL row-level security is not enabled; isolation is enforced in the application and tested.
6. Browser-based field acceptance must be repeated on the organization’s target phones/tablets and network conditions.
7. Final customer branding/legal language and capability catalog require business approval.
8. Backup and restore must be tested in the target Render/object-storage accounts.

## Recommended release gate

Deploy first to a separate staging environment and execute the production sign-off checklist in [`DEPLOYMENT.md`](DEPLOYMENT.md). Do not enable confidential AI or upload real customer information until security, privacy, storage, and retention controls are approved.
