# AI Enhancement Status — v0.8.10

## Purpose
Provide a compact, persisted workflow-status indicator directly beneath each section-level **AI Enhance** button so users do not need to scroll to the AI Assistance inspector to determine whether wording has been generated or accepted.

## Status contract
- **Not Run** — no `OBSERVATION_ENHANCEMENT` suggestion exists for the section.
- **Not Reviewed** — at least one observation enhancement exists and the latest suggestion is not `APPROVED`. This intentionally includes pending, rejected, stale, superseded, or otherwise non-accepted latest attempts because the three-state UI answers whether the latest AI wording is accepted.
- **Accepted** — the latest observation enhancement suggestion is `APPROVED`.

## Ordering
The latest suggestion is determined by `created_at` descending. A new generation after a previously accepted suggestion therefore returns the status to **Not Reviewed** until the new result is accepted.

## UI
The status is rendered in small secondary text immediately below the **AI Enhance** button as `Status: <value>`. It is updated live when a suggestion becomes available and refreshed from persisted report data on navigation/reload.

## Non-goals
No schema migration, new AI workflow, new review state, or new Render setting is introduced. Existing suggestion history remains the source of truth.
