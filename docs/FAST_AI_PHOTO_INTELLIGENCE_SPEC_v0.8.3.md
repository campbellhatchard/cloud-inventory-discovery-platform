# Fast AI Wording and Independent Photo Intelligence Specification — v0.8.3

## Objective

Reduce perceived and actual latency for Current Operations wording enhancement while strengthening the separation between written discovery evidence, independent visual evidence, and AI interpretation.

The release replaces the combined wording-plus-photo enhancement pipeline with two independent workflows:

1. **Fast AI Enhanced Wording** — text-only generation with draft-first display and source verification.
2. **AI Photo Analysis** — independent image understanding followed by a separate optional comparison against written Current Operations.

## Fast AI Enhanced Wording

### Source scope

The initial wording request may use only written current-state sources from the selected section:

- Current Operations narrative;
- active guided discovery responses;
- non-rejected formal Findings; and
- recorded Metrics.

Photographs are not included in the wording request and `OBSERVATION_ENHANCEMENT` rejects supplied evidence IDs.

### Draft-first processing

The wording pipeline is split into two visible stages.

**Generation stage**

- One lean, text-only model request creates the professional wording draft.
- The request uses low reasoning effort, low response verbosity, and a bounded output size.
- The draft is persisted immediately as the pending AI suggestion.
- The AI job enters `VERIFYING` and the browser may display the draft immediately.
- Acceptance is disabled while verification is incomplete.

**Verification stage**

- A second source-grounded call checks every factual claim against the written source snapshot.
- If unsupported wording is detected, one constrained repair call is permitted followed by re-verification.
- Acceptance is enabled only when final verification is `PASSED`.

The browser no longer imposes the previous fixed 90-poll / approximately 135-second timeout. Closing the comparison modal leaves the worker job running.

## Independent photo analysis

### First-stage visual analysis

A photograph is analyzed without written process context. The model does not receive Current Operations, guided responses, Findings, or the user-supplied caption as contextual evidence during this stage.

The first pass returns:

- `visible_observations` — directly supportable visual facts;
- `operational_interpretations` — cautious operational interpretations;
- `uncertainties` — statements that cannot safely be concluded;
- `detail_used`; and
- `detail_escalation_reason`.

The first request uses image detail `low`. The model may request one `high` detail pass only when fine labels, screens, small objects, or dense spatial detail could materially alter the operational observation.

### Cache behavior

Independent photo analysis is stored in the existing `EvidenceAiObservation` record and keyed to the preferred image file SHA-256. A SHA-matched result is returned as `CACHED` without another model call. Moving an evidence item between report sections updates the cached observation's section reference without invalidating the visual analysis.

### Multi-photo processing

The section-level **AI Photo Analysis** workspace allows users to select one or more photographs. Each uncached photograph receives its own `PHOTO_ANALYSIS` AI job. Users may close the progress window and continue working while jobs remain queued or running.

## Photo-to-written-context comparison

After independent analysis exists, the user may select **Compare to Current Operations**.

This second AI stage receives:

- written discovery sources; and
- stored independent photo observations.

The original image bytes are not sent again.

The response explicitly separates:

- `supports`;
- `adds_context`;
- `potential_conflicts`;
- `open_questions`; and
- a `suggested_text` revision.

The suggested narrative is verified against both written sources and stored visual observations. One repair and re-verification pass is permitted when unsupported claims are detected. Applying an approved revision creates a new `CURRENT_OPERATIONS` content version with source type `AI_PHOTO_CONTEXT` and preserves the prior version.

## Queue and worker isolation

The generic FIFO worker queue is extended with `queue_name` and `priority` fields. The Worker starts independent processing lanes:

- `FAST_TEXT` — Current Operations wording, highest interactive priority;
- `PHOTO_ANALYSIS` — independent visual analysis;
- `GENERAL_AI` — solution, benefit, report-quality, executive-summary, demo, and photo-context work;
- `PUBLICATION` — DOCX/PDF publication processing.

PostgreSQL row locking with `SKIP LOCKED` continues to protect concurrent claims. Separating the lanes prevents a long photograph-analysis request from monopolizing the processing path used by fast text generation or publication.

## Performance telemetry

AI jobs retain model usage and stage timing where available. v0.8.3 records timing for:

- wording draft generation;
- wording verification/repair;
- independent photo analysis;
- photo-context revision; and
- total job duration.

Administration continues to expose safe aggregate AI and Worker health information. No credentials or raw confidential prompts are exposed through the operations dashboard.

## Governance

- AI remains disabled unless the configured policy gate permits confidential processing.
- `store=False` remains in use for model requests.
- No AI-generated wording is automatically written into the report.
- Written wording acceptance requires successful factual verification.
- Photo observations distinguish direct visual facts from cautious interpretations and uncertainties.
- Photo-context revisions require human application and preserve version history.
- No Cloud Inventory capability, benefit, or solution claim is introduced by the current-operations photo workflow.

## Database

Alembic revision: `h38e1f7c5a88_ai_latency_photo_intelligence.py`.

The migration adds `queue_name` and `priority` to `jobs` and creates supporting indexes. Existing queued work receives the `STANDARD` queue and priority `100`.

## Environment impact

No new environment variables are required. Existing PostgreSQL, Cloudflare R2, OpenAI, Zero Data Retention policy, LibreOffice, Web, and Worker configuration is reused.
