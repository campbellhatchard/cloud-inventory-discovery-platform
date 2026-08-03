# Release Notes - v0.6.0

## AI Observation Enhancement
- Adds **AI Enhance** to every report section except Quick Entry and Report.
- Adds side-by-side original vs AI-enhanced current-operations wording.
- Adds selected-photo vision analysis using the configured multimodal OpenAI model.
- Adds source-grounded generation, factual verification, and an automatic unsupported-claim repair pass.
- Adds natural-language refinement of an AI suggestion.
- Adds browser text-to-speech for the proposed wording.
- Adds controlled acceptance that replaces the report narrative only after verification passes.
- Preserves original wording and accepted AI wording in section version history.
- Prevents stale AI suggestions from overwriting newer collaborative edits.
- Moves Render AI enablement and confidential-processing flags to externally managed environment variables and adds the missing OpenAI key/project declarations.

## Existing functionality
Report output formatting, collaborative capture, R2 storage, publication history, prospect onboarding, Quick Entry, and report-level workflow remain unchanged.
