# Release Notes — v0.8.3

## Fast AI Wording and Independent Photo Intelligence

### Fast wording

- Current Operations **AI Enhance** is now text-only and no longer waits for selected photographs.
- The initial draft uses a lean low-reasoning, low-verbosity request with bounded output.
- The wording draft is committed and displayed before factual verification finishes.
- Acceptance remains disabled until source verification passes.
- One controlled repair and re-verification pass remains available for unsupported claims.
- Removed the browser-side fixed 90-poll / approximately 135-second AI wording timeout.
- Closing the AI modal no longer implies the background job failed or was cancelled.

### Independent photo intelligence

- Added an **AI Photo Analysis** workspace to each operational section.
- Users can select one or several photographs for independent analysis.
- First-stage photo analysis does not receive Current Operations, guided responses, Findings, or the photo caption as process context.
- Visual output separates visible observations, cautious operational interpretations, and uncertainties.
- Photo analysis starts with low image detail and may escalate once to high detail when fine visual detail is material.
- Existing SHA-based `EvidenceAiObservation` caching is retained and now surfaced directly to the user.
- Added **Compare to Current Operations**, which uses cached visual observations plus written discovery without re-sending the image.
- Photo-context comparison separates supported content, added context, potential conflicts, and open questions before suggesting revised wording.
- Applied photo-context revisions preserve Current Operations history using source type `AI_PHOTO_CONTEXT`.

### Queue and worker processing

- Added `queue_name` and `priority` to background jobs.
- Added independent worker lanes for `FAST_TEXT`, `PHOTO_ANALYSIS`, `GENERAL_AI`, and `PUBLICATION`.
- Fast text jobs use higher interactive priority than general AI processing.
- Publication processing is isolated from long-running AI requests.
- Added stage timing telemetry for the new workflows.

### Database

Alembic revision: `h38e1f7c5a88_ai_latency_photo_intelligence.py`.

### Environment impact

No new environment variables are required. Existing OpenAI model, API key, Zero Data Retention policy, PostgreSQL, Cloudflare R2, and LibreOffice configuration is reused.
