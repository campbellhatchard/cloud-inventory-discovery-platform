# Release Notes — v0.7.1

## Manual Cloud Inventory Approach entry

- Replaces the read-only/empty Cloud Inventory Approach presentation with an editable narrative field.
- Users can type directly, map approved capabilities, generate with AI, or combine all three methods.
- Manual text autosaves after typing pauses.
- Unsaved manual text is flushed before AI generation starts.
- Manual entries are stored as controlled `USER` content versions.
- AI-accepted entries remain stored as `AI_ACCEPTED` versions.
- Version history retains all prior manual and AI versions.
- Optimistic concurrency prevents a stale browser session from overwriting another user's approach.
- Current manual text flows into report preview and generated documents.

## Deployment impact

- No database migration.
- No new environment variables.
- No changes to R2 or OpenAI configuration.
- Blueprint sync is required to update `APP_VERSION` to `0.7.1` for Web and Worker.
