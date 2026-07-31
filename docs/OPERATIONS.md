# Operations, Retention, and Recovery

## Daily operating checks

- Web `/readyz` is healthy.
- Worker is running and polling.
- No publication or AI jobs remain queued beyond the expected processing window.
- No repeated job failures.
- PostgreSQL storage, connections, and CPU remain within limits.
- Object-store access and upload/download checks succeed.

## Job recovery

Generic jobs retry up to their configured maximum with exponential delay. Domain records retain status/error details.

### Publication failure

1. Open the publication status in the application/API.
2. Review worker logs for DOCX generation, object storage, or LibreOffice errors.
3. Correct the underlying issue.
4. Request a new publication; publication records are revision snapshots and are not overwritten.

### AI failure

1. Inspect `/api/ai-jobs/<id>`.
2. Verify policy settings and API credentials.
3. Verify the worker has the same AI environment settings as the web service.
4. Correct the problem and submit a new request if retry has exhausted.
5. Never manually mark failed AI output as approved.

## Backups

At minimum:

- enable Render PostgreSQL backups appropriate to the environment;
- document database restore into a separate staging database;
- protect object storage with provider durability/versioning settings where approved;
- retain configuration/secrets in an approved secrets-management process;
- keep generated prospect exports according to internal policy.

A database backup without matching objects is incomplete. A bucket copy without the database cannot reconstruct relationships and permissions. Recovery planning must cover both.

## Restore drill

Quarterly or after major schema changes:

1. Restore PostgreSQL into an isolated test environment.
2. Point a staging deployment at a copied/test object-store bucket.
3. verify login and access isolation;
4. open representative reports and images;
5. generate DOCX and PDF;
6. run prospect export;
7. document recovery time, missing objects, and corrective actions.

## Retention lifecycle

Default retention is 1,095 days from prospect creation unless configured otherwise.

### Warning phase

`RETENTION_WARNING_DAYS` before the due date, maintenance changes active prospects to `RETENTION_REVIEW` and records an audit event. Administrators use the retention dashboard to decide whether to:

- extend retention under organizational policy;
- place a legal hold;
- export and archive;
- export and permanently delete.

### Archive

Archive prevents the record from being treated as active work but preserves the prospect, reports, evidence, and publications. Export before archival is strongly recommended.

### Permanent deletion

Prospect deletion is intentionally destructive. The API refuses deletion when:

- legal hold is active;
- an export has not been completed;
- the exact prospect name is not confirmed;
- export acknowledgement is false.

Deletion removes database records through cascades and deletes associated private objects. Verify the exported ZIP before deletion.

## Merge-source recovery

When an owner chooses to delete source reports after merge, the source is first marked `MERGED` and receives a recovery-delete timestamp. Maintenance deletes it only after `MERGE_SOURCE_RECOVERY_DAYS`.

This is not a substitute for reviewing merge conflicts and confirming target completeness before merge completion.

## Export contents

A prospect export ZIP includes:

- manifest and metadata;
- structured JSON datasets for prospect-owned records;
- stored evidence/publication objects available to the application.

Exports are generated to a temporary file and streamed to the authorized administrator/owner. Treat exports as highly confidential.

## Object reconciliation

Periodically compare:

- every `file_objects.storage_key` against object-store existence;
- unexpected object-store keys against database records;
- object hashes for a sample of critical publications.

Do not automatically delete orphan objects until the cause has been investigated and a backup exists.

## Database maintenance

- Monitor slow queries and index usage as data grows.
- Apply Alembic migrations through controlled deployment.
- Do not edit production tables manually except under an approved recovery procedure.
- Keep application and worker versions aligned with the database schema.

## Capacity planning

Primary growth drivers:

- number and resolution of site photographs;
- attachment volume;
- generated publication history;
- extracted text size;
- audit events;
- AI suggestion history.

Track average evidence bytes/report, reports/prospect, publication generation duration, and oldest queue age. Resize the worker before large report conversions become unreliable.
