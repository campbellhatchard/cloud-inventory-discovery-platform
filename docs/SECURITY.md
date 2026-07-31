# Security and Privacy

## Security objective

The platform stores prospect-confidential operational information, photographs, system details, and solution recommendations. Security controls therefore prioritize prospect isolation, least privilege, controlled publication, auditable changes, and prevention of unsupported AI/product claims.

## Authentication

- Application-managed usernames and passwords
- Argon2id password hashing
- First-login password change for bootstrap users
- Server-side sessions with configurable expiry
- Secure, HTTP-only, same-site cookies in production
- Login failure counting and account lockout
- CSRF token required for state-changing browser requests
- Explicit logout and session invalidation

The bootstrap password exists only as an environment secret during initialization. It must be unique per environment and changed immediately after first login.

## Authorization

Roles:

- **Contributor** — capture and edit authorized report content.
- **Reviewer** — contributor rights plus approval of AI suggestions, capability mappings, benefits, and evidence inclusion.
- **Owner** — reviewer rights plus report structure, merge, finalization, archive, and report-deletion decisions.
- **Administrator** — global user, branding, capability, knowledge, retention, and audit administration.

Authorization is checked for every prospect, report, section, file, AI job, and publication request. Object keys are not treated as authorization tokens.

## Prospect isolation

Prospect-owned data carries a prospect identifier directly or through a parent report. The API first establishes authorized prospect/report access and then validates the requested child record belongs to that scope.

The automated test suite covers cross-prospect access denial. This is application-layer isolation. PostgreSQL row-level security is not enabled in v0.2.0 and can be considered as defense in depth in a future release.

## Browser controls

Responses include:

- Content Security Policy restricted to the same origin;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- HSTS in production;
- restrictive referrer and permissions policies;
- unique request ID.

The PWA caches only the application shell. Prospect API data is not deliberately cached by the service worker.

## Upload security

Controls implemented:

- configurable maximum file size;
- normalized safe filename;
- narrow allowlist of file types;
- PDF magic-header validation;
- DOCX/XLSX ZIP structure validation;
- text/binary sanity check;
- image decoding and recompression through Pillow;
- private object storage;
- SHA-256 hash and file metadata;
- no direct execution of uploaded content.

### Known gap: antivirus scanning

The application records scan state but does not ship with a malware engine. Allowlisting and structural validation are not substitutes for antivirus scanning. Before broader production adoption, select one of:

1. upload quarantine plus an external scanning service;
2. object-store event scanning with promotion to a clean prefix;
3. an approved API malware scanner;
4. an internal gateway that scans before the application accepts the file.

Until then, uploaded office/PDF attachments should be treated as untrusted when downloaded.

## Object storage

- Bucket must be private.
- Credentials should be scoped to the application bucket.
- Production uses S3-compatible storage, not a local Render filesystem.
- Download authorization occurs in the application before local streaming or a short-lived signed URL is returned.
- Object keys are prospect namespaced.
- Storage and database deletion are coordinated for report/prospect deletion.

## AI privacy and governance

AI is disabled by default. Confidential processing is gated by:

- `AI_ENABLED=true`;
- `AI_CONFIDENTIAL_CONTENT_ENABLED=true`;
- configured API key;
- `OPENAI_DATA_CONTROL_MODE=zero_data_retention`.

The application calls the Responses API with `store=False`. OpenAI configuration must nevertheless be reviewed at the organization/project level because application flags cannot create a contractual or account-level Zero Data Retention entitlement.

The application does not use OpenAI background mode. AI requests are queued internally and then sent as ordinary server-side API requests so the platform can retain its own job state without requiring provider-side background storage.

AI context is minimized to the selected report/section, extracted supporting evidence, findings, approved knowledge, and approved capability records. Prospect-specific knowledge is not shared with another prospect unless an administrator explicitly de-identifies and approves it for reuse.

Every AI output is stored as `PENDING`. A human reviewer must approve it before it can alter narrative, create a capability mapping, or create a benefit.

## Secrets

Store only in Render secrets/environment settings:

- database connection string;
- bootstrap administrator password;
- object-store credentials;
- OpenAI API key/project ID.

Never place secrets in:

- Git history;
- browser JavaScript;
- logs;
- generated documents;
- seed CSV files;
- support tickets or screenshots.

Rotate a secret immediately if exposure is suspected.

## Audit

Audit events cover authentication-relevant administrative changes and material workflow operations, including:

- user and membership actions;
- report/section changes;
- uploads;
- merge;
- AI request/review;
- capability/benefit review;
- validation/publication;
- archive/export/delete;
- retention maintenance.

Audit records are append-only through the application. Database administrators remain technically capable of changing them; infrastructure/database access must therefore be restricted and logged separately.

## Retention and deletion

Default prospect retention is three years. The worker moves approaching records into retention review. Permanent prospect deletion requires:

- administrator role;
- no legal hold;
- completed export;
- exact prospect-name confirmation;
- explicit acknowledgement that export was completed.

Draft or merged reports can be permanently deleted using exact title confirmation. Finalized customer publications are preserved with the prospect unless the prospect is deleted under the controlled process.

## Incident response minimums

1. Disable affected accounts and revoke sessions.
2. Rotate relevant application, database, storage, and AI credentials.
3. Preserve logs and audit records.
4. Determine affected prospect IDs and objects.
5. Suspend worker/AI processing if integrity or confidentiality is uncertain.
6. Restore from a verified backup where required.
7. Follow organizational legal, customer, and regulatory notification procedures.
