# Durable AI Wording Persistence and Refinement Lineage — v0.8.4

## Objective

Extend the locked v0.8.3 fast-AI/photo-intelligence baseline so unaccepted AI wording remains durable, reusable, and auditable. Reopening a report must restore the prior wording when the written source content is unchanged instead of creating another model request.

## Source validity boundary

Each text-only Current Operations request receives a SHA-256 `source_fingerprint` calculated from a canonical representation of:

- report and section identity;
- section title and process module;
- Current Operations narrative;
- active guided responses;
- non-rejected findings; and
- section metrics.

Photographs, timestamps, job status, and volatile processing metadata are excluded. Any change to the written evidence packet changes the fingerprint.

## Durable suggestion behavior

1. The generated draft is committed to `ai_suggestions` before verification completes.
2. The AI job enters `VERIFYING`, but the user-visible wording remains persisted.
3. Opening AI Wording first requests the current saved candidate from the server.
4. If a pending suggestion or in-flight job has the same source fingerprint, it is restored and no new model job is created.
5. Elapsed time, browser closure, logout, device change, or reopening the report does not invalidate the suggestion.
6. A new model job is created only when:
   - no matching saved candidate exists;
   - the written sources changed; or
   - the user explicitly selects **Generate another version**.

The API independently enforces this behavior. Frontend behavior is not the sole duplicate-prevention control.

## Stale-source behavior

When the current source fingerprint differs from the stored suggestion fingerprint:

- the prior wording remains available for history;
- it is displayed as stale;
- acceptance is blocked;
- refinement is blocked; and
- the user is directed to **Generate updated wording**.

Once a replacement draft is persisted, prior pending candidates are classified as:

- `SUPERSEDED` when based on the same source fingerprint; or
- `STALE` when based on different written evidence.

## Refinement contract

A refinement request is a controlled edit of the immediately preceding AI suggestion. The model receives three distinct inputs:

1. `base_ai_wording` — the prior suggestion's current enhanced text;
2. `refinement_request` — the user's exact instruction; and
3. `source_material` — the current written evidence used only as factual authority.

The prompt requires preservation of unaffected wording and prohibits redrafting from scratch unless the instruction requires it.

A refinement cannot proceed without a non-empty instruction or when the parent suggestion's fingerprint no longer matches the current written sources.

## Database lineage

The v0.8.4 migration adds:

### `ai_jobs`

- `source_fingerprint`

### `ai_suggestions`

- `source_fingerprint`
- `parent_suggestion_id`
- `base_ai_text`
- `refinement_instruction`
- `superseded_by_suggestion_id`

The child suggestion stores an immutable snapshot of the base wording and refinement instruction even though the parent remains available. This protects auditability during later migration, archival, or repair.

## API behavior

### Retrieve current wording

`GET /api/reports/{report_id}/sections/{section_id}/ai-wording/current`

Returns one of:

- matching saved suggestion;
- matching in-flight job;
- stale prior suggestion; or
- no saved wording.

### Request wording

`POST /api/reports/{report_id}/ai`

For `OBSERVATION_ENHANCEMENT`, the endpoint is idempotent by default. `force_regenerate=true` explicitly creates an alternative request from unchanged sources.

## Acceptance controls

Acceptance checks the current fingerprint against the stored fingerprint. The section version remains a compatibility fallback for legacy suggestions that do not yet carry fingerprint metadata.

## Backward compatibility

Existing v0.8.3 suggestions may have null database fingerprint columns. When encountered, the application derives the fingerprint from the stored `source_snapshot` and reuses the existing suggestion when valid.

## Non-goals

- No time-based expiration of valid pending wording.
- No automatic acceptance.
- No change to independent photo analysis or photo-context revision.
- No provider-side persistent storage or changed AI retention policy.
