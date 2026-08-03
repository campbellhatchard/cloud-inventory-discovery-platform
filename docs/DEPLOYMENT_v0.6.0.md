# Deployment Guide - v0.6.0

## Base
- Locked base: `baseline-v0.5.2`
- Expected base commit: `eea03d28e7cbf9963f8a5d877a0b3639bd0c4f9f`
- Feature branch: `feature/ai-observation-enhancement-v0.6.0`

## Render configuration required for AI
Both the web service and worker should use the same AI policy/model settings. The worker requires `OPENAI_API_KEY` because AI jobs are executed there.

Set these environment variables deliberately; do not commit secrets:
- `OPENAI_API_KEY`
- `OPENAI_PROJECT_ID` (optional)
- `OPENAI_MODEL=gpt-5-mini` unless another approved text+image model is selected
- `AI_ENABLED=true`
- `AI_CONFIDENTIAL_CONTENT_ENABLED=true` only after confidential AI processing has been approved
- `OPENAI_DATA_CONTROL_MODE=zero_data_retention` only when the OpenAI project is actually configured for the approved ZDR posture

R2 settings must remain valid on the worker when photographs are included in AI analysis.

## Deployment
Use the release PowerShell installer. It validates from the locked baseline, runs the complete staging validation, commits only after validation succeeds, pushes the feature branch, and optionally fast-forwards staging. After the push, Sync Blueprint because the AI environment-variable ownership changes in the Blueprint, then manually deploy both web and worker.
