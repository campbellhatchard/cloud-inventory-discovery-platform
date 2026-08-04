# Release Notes — v0.8.4

## Durable AI wording

- Restores saved unaccepted Current Operations wording when the written source evidence is unchanged.
- Prevents duplicate AI jobs at the API layer, including across browsers and devices.
- Adds a deterministic SHA-256 source fingerprint covering narrative, guided responses, findings, metrics, and section context.
- Preserves drafts committed before verification finishes, allowing users to close the window and return later.
- Adds **Generate another version** for intentional alternatives from unchanged sources.
- Displays prior wording as stale and blocks acceptance or refinement when written evidence changes.

## Refinement lineage

- Sends the immediately preceding AI wording, the user's exact refinement request, and current written evidence.
- Directs the model to preserve unaffected wording rather than redraft from scratch.
- Stores parent suggestion, immutable base wording, refinement instruction, source fingerprint, and supersession linkage.
- Marks same-source prior candidates `SUPERSEDED` and changed-source candidates `STALE` after a replacement draft is persisted.

## Schema and API

- Adds Alembic revision `i49f2a8d6b99` over v0.8.3 revision `h38e1f7c5a88`.
- Adds `GET /api/reports/{report_id}/sections/{section_id}/ai-wording/current`.
- Adds `force_regenerate` to AI requests.
- Extends AI job and suggestion responses with fingerprint and lineage metadata.

## Compatibility

Independent photo analysis, photo-context comparison, fast-text priority lanes, publication processing, and existing report version history remain unchanged.
