# v0.8.10 Release Notes

## AI enhancement status
Each operational section now shows a compact workflow status directly beneath **AI Enhance**.

- **Not Run** — no Current Operations AI wording has been generated for the section.
- **Not Reviewed** — the latest generated wording has not been accepted.
- **Accepted** — the latest generated wording was approved and applied.

The status is derived from persisted `OBSERVATION_ENHANCEMENT` suggestion history and updates live when a saved result appears. Creating a newer AI version after an accepted version returns the status to Not Reviewed until that new version is accepted.

There is no schema migration and no new environment configuration. v0.8.9 Unified Current Operations Narrative behavior remains unchanged.
