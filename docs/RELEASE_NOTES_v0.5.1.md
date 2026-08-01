# Release Notes — v0.5.1

## Collaborative Capture & R2 Storage Readiness

v0.5.1 removes per-section assignment and workflow status from the discovery experience. All associated contributors can collaborate directly in report sections, and the Report page now compiles content as soon as reportable information is captured.

### Added
- Report-level status: Draft / Ready for review / Finalized.
- Direct Draft Word download.
- Direct Draft PDF download.
- Persistent storage configuration status on the Report page.
- Controlled detection of placeholder/invalid S3 endpoint configuration.
- Alembic migration `a61d9e7c4b10`.

### Changed
- Section lifecycle is internal ACTIVE/REMOVED only.
- Existing section assignments are cleared.
- Report preview is content-driven rather than section-status-driven.
- Final validation checks report readiness instead of section readiness.
- Draft document generation can proceed when R2 is not configured.

### Persistent storage dependency
Cloudflare R2 is still required for evidence/attachments, prospect logos, stored/generated publications, workspace exports, and final controlled publication storage. Configure the Render web service and worker with the same R2 endpoint, bucket, Access Key ID, and Secret Access Key.
