# Collaborative Capture & R2 Storage Specification — v0.5.1

## Release objective
Simplify discovery capture so section assignment and section workflow status no longer gate contribution or report assembly, move workflow status to the report, and make draft report downloads usable before persistent Cloudflare R2 storage is configured.

## Functional changes

### Collaborative section capture
- Remove the Assigned contributor control from section screens.
- Remove section workflow status controls and status badges.
- Any user with report/prospect contributor access can enter section narrative, guided responses, findings, metrics, and Quick Entry content.
- Retain only an internal ACTIVE/REMOVED section lifecycle to preserve section removal and audit behavior.
- Existing section assignments are cleared by migration.
- Existing non-removed section workflow states are normalized to ACTIVE.

### Content-driven Report page
- The Report page compiles every active section containing reportable content.
- Reportable content includes narrative, responses, findings, and available evidence.
- No section completion/status step is required before content appears in the draft preview.
- The Report page shows counts for sections with content, empty sections, and the current report revision.

### Report-level workflow state
- Report workflow uses DRAFT, READY_FOR_REVIEW, and FINALIZED.
- Reviewers/owners can move a report between DRAFT and READY_FOR_REVIEW.
- FINALIZED remains system-controlled after successful final publication.
- Final validation requires READY_FOR_REVIEW (or an already FINALIZED report).
- Section status is not part of final validation.

### Draft document downloads
- Add direct authenticated Word and PDF draft download endpoints.
- Draft download generation does not require persistent R2 storage to be configured.
- If persistent evidence/custom branding cannot be read because storage is unavailable, draft generation continues and records an evidence-unavailable note instead of failing the entire document.

### Persistent Cloudflare R2 storage
- Validate S3/R2 configuration before creating the boto3 client.
- Detect the placeholder endpoint `https://<cloudflare-account-id>.r2.cloudflarestorage.com` and return a controlled configuration error.
- Add authenticated `/api/storage/status` to expose whether persistent storage settings are syntactically configured without exposing credentials.
- Controlled/stored publications, evidence, prospect logos, workspace exports, and stored files continue to use R2.

## Migration
Revision `a61d9e7c4b10`:
- clears `report_sections.assigned_to_user_id`;
- changes every non-removed section state to `ACTIVE`;
- preserves `REMOVED` sections;
- does not delete report content.

## Backward compatibility
The section state and assignment database columns remain in place to avoid destructive schema changes. They are no longer presented as workflow controls. Assignment data is intentionally cleared because it no longer has operational meaning.
