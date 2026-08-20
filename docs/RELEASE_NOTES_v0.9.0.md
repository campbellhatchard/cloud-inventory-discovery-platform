# Release Notes v0.9.0 — Fast AI Wording & Photo Intelligence

## Scope

v0.9.0 layers four enhancements onto the current v0.8.11 staging baseline without changing the simplified operational-section UI, accepted narrative behavior, refinement lineage, or human-review controls.

### Fast AI wording

- Current Operations AI wording now uses a dedicated `ai.fast-wording` worker job.
- The first response is intentionally limited to text rewriting from written sources only.
- Source verification and any repair pass run later on the independent `AI_VERIFICATION` queue.
- OpenAI SDK request timeouts are explicit and SDK retries are disabled for these bounded calls; the application job queue remains responsible for retry behavior.
- Existing saved-wording restoration, source fingerprints, refinement lineage, stale detection, and acceptance rules are retained.

### Photo Intelligence

- New `PHOTO_AI` worker lane is independent from fast wording and general AI.
- Each photograph is first analyzed without captions or Current Operations Narrative context.
- The independent visual analysis is cached on the evidence record and keyed by the stored file fingerprint.
- Editing the narrative does not rerun image analysis.
- A second explicit step correlates cached photo analysis with the Current Operations Narrative and proposes a revision.
- Proposed revisions remain separate until a user accepts or rejects them.
- Acceptance writes a new Current Operations content version and preserves the original narrative in version history.
- Stale photo revisions cannot be accepted after the underlying narrative or photo set changes.

### Quick Entry

- `Master Data` is now available as an Area of Operation and maps directly to the existing `master-data` report section.
- `Other` maps to the existing `general-observations` stable section.

### Navigation

- Existing `General Operational Observations` content is preserved.
- The page is relabeled `Other` and moved to display order 255, directly beneath `Manufacturing` (250) and before `Cross-Process Findings and Dependencies` (260).
- The upgrade is idempotent and is applied when the application starts, so existing reports and templates retain their content and identifiers.

## New optional environment settings

- `OPENAI_FAST_TEXT_MODEL` — defaults to `OPENAI_MODEL` when unset.
- `OPENAI_ANALYSIS_MODEL` — defaults to `OPENAI_MODEL` when unset.
- `OPENAI_REQUEST_TIMEOUT_SECONDS` — default 30 seconds.
- `OPENAI_PHOTO_REQUEST_TIMEOUT_SECONDS` — default 60 seconds.

## Data handling

Photo Intelligence uses image input through the existing Responses API path with `store=False`. Organization/project data-control requirements must remain satisfied before confidential customer photographs are processed.
