# Architecture

## Design objective

The platform is designed as an internal, prospect-isolated evidence and report workflow rather than a general-purpose document editor. Structured records remain the system of record; DOCX and PDF files are generated publication artifacts.

## Components

### Browser/PWA

The frontend is a responsive vanilla-JavaScript single-page application served by FastAPI. It provides:

- mobile-first quick capture;
- device-camera file selection;
- autosave and IndexedDB-backed retry queue;
- report navigation, section editing, reviewer actions, and administration;
- service-worker caching of the application shell.

The PWA is resilient to transient loss of connectivity, but it is not intended to support fully disconnected multi-day collaboration.

### FastAPI web service

The web service handles:

- authentication and session enforcement;
- authorization and prospect/report isolation;
- CRUD and collaboration APIs;
- evidence validation and storage;
- validation and publication requests;
- audit events;
- queue insertion and job-status endpoints.

Long-running AI and publication work is not performed in the web request.

### PostgreSQL

PostgreSQL is the production system of record for:

- users, roles, sessions, prospects, memberships;
- sites, engagements, reports, sections, prompts, answers;
- findings, metrics, evidence metadata, capability mappings, benefits;
- comments, approvals, AI jobs/suggestions, publications;
- capability and knowledge governance;
- queue state, retention state, and audit events.

SQLite is supported only for local development and automated tests.

### Object storage

Private S3-compatible object storage holds binary content:

- original and web-optimized images;
- supporting documents;
- generated DOCX and PDF publications;
- export packages.

Keys are namespaced beneath `prospects/<prospect-id>/...`. Database records remain the authority for access; a user cannot retrieve a file unless they can access its prospect/report.

### Background worker

The worker claims jobs from the database with row locking on PostgreSQL. It performs:

- `publication.generate` — immutable DOCX/PDF publication generation;
- `ai.generate` — OpenAI generation and pending-suggestion creation;
- periodic retention review and expired merged-report cleanup.

The job model supports retries with exponential delay. Publication and AI domain records also expose their own status and error information.

## Domain hierarchy

```text
Prospect
  Site
  Engagement
  Report
    Report Section
      Prompt Response
      Finding
      Metric
      Evidence
      Comment
    Capability Mapping
    Benefit
    AI Job / Suggestion
    Publication
```

## Access model

Access is additive and explicit:

- administrators can access all records;
- prospect memberships provide prospect access;
- report memberships provide report-specific access;
- an engagement/report owner controls structure, merge, final validation, and deletion decisions;
- reviewers approve solution claims and AI output;
- contributors capture and edit assigned content.

Every prospect-owned lookup is checked before the record or object is returned. This is application-layer isolation; it is not PostgreSQL row-level security in v0.2.0.

## Collaboration model

The application uses section-level optimistic concurrency:

1. The browser reads a section and its version.
2. An update includes `expected_version`.
3. The server rejects stale writes with HTTP 409 and returns the current version/content.
4. The user reloads and reconciles rather than silently overwriting another contributor.

Comments, assignments, approvals, and audit events supplement this model. Real-time keystroke co-editing is intentionally out of scope.

## Merge model

An owner can merge multiple source reports into a target report. The operation:

- clones structured content and evidence;
- records source-to-target lineage;
- identifies narrative conflicts;
- can mark source reports as `MERGED`;
- retains merged sources for a configurable recovery period before automated deletion.

## AI grounding and control flow

```text
User requests assistance
  -> policy gate
  -> AiJob QUEUED
  -> worker builds scoped context
       report/section evidence
       extracted attachments
       findings
       approved prospect knowledge
       approved reusable knowledge
       approved capability catalog
  -> Responses API, store=False
  -> AiSuggestion PENDING
  -> human review
  -> approved text/mappings/benefits applied
```

AI never publishes directly. Cross-prospect knowledge must be explicitly reviewed and de-identified before it becomes reusable.

## Publication architecture

A publication request captures report revision, output type, and draft/final status. The worker generates:

1. editable DOCX using controlled Word styles;
2. PDF via headless LibreOffice;
3. private object-store records with hashes and immutable filenames.

Drafts receive the configured `DRAFT - CONFIDENTIAL` watermark. Final publication requires blocking validation to pass.

## Trust boundaries

1. **Browser to web:** session cookie, CSRF token, TLS in production.
2. **Web/worker to database:** private Render connection string.
3. **Web/worker to object storage:** secret S3-compatible credentials and private bucket.
4. **Worker to OpenAI:** API key and approved data-control configuration.
5. **Document conversion:** local LibreOffice process operating on temporary files.

## Scaling characteristics

- Web services are stateless with respect to binary files and can scale horizontally.
- The database queue supports multiple workers on PostgreSQL using `FOR UPDATE SKIP LOCKED`.
- Object storage removes the single-instance limitations of local/persistent disks.
- Heavy reports remain constrained by worker CPU/memory and LibreOffice conversion time; worker sizing and timeouts must be tested using representative large reports.
