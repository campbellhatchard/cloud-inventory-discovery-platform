# AI Observation Enhancement Specification - v0.6.0

## Objective
Provide a controlled, source-grounded AI editing workflow for each report section except Quick Entry and Report. The workflow improves current-operations wording from user-entered observations and explicitly selected section photographs without introducing unsupported facts.

## User flow
1. User selects **AI Enhance** from a report section.
2. A side-by-side comparison modal opens. Original entered material is shown on the left.
3. Section photographs are selected for AI analysis by default and can be deselected.
4. The worker analyzes selected images, generates an enhanced customer-facing narrative, and runs a second factual-support verification pass.
5. The right panel shows enhanced wording, source references, gaps, verification status, and a browser text-to-speech control.
6. The user can refine the result with a natural-language instruction. Each refinement is a new AI suggestion linked to the prior suggestion.
7. **Accept enhanced text** is enabled only when factual verification passes.
8. Acceptance replaces the current section narrative for report output while preserving the original narrative and accepted AI version in section content history.

## Hallucination controls
- Current-operations generation receives no capability catalogue or reusable product knowledge.
- Sources are limited to the selected section's narrative, guided responses, findings, metrics, and selected photographs.
- Image interpretation is separately constrained to visible observations, cautious operational interpretations, and explicit uncertainties.
- A factual-support verifier blocks acceptance when unsupported claims remain.
- One automatic repair pass attempts to remove unsupported claims before a suggestion is presented as acceptable.
- Section version is checked at acceptance time so an AI suggestion cannot overwrite newer collaborative edits.

## Data model
- `section_content_versions` stores retained current-operations versions and the accepted AI version.
- `evidence_ai_observations` caches visual observations for immutable evidence files.
- `ai_jobs.context_snapshot` stores the exact source packet captured when an enhancement was requested.
- `ai_jobs.parent_suggestion_id` links natural-language refinement turns.

## AI configuration
The release preserves the existing confidential-data policy gate. AI requires `AI_ENABLED=true`, `AI_CONFIDENTIAL_CONTENT_ENABLED=true`, an `OPENAI_API_KEY`, and an approved `OPENAI_DATA_CONTROL_MODE=zero_data_retention` configuration. R2 must be configured when photographs are selected because the worker reads the stored image bytes for vision analysis.
