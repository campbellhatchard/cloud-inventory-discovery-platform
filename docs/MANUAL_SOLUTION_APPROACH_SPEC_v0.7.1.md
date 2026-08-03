# Manual Cloud Inventory Approach Entry — v0.7.1

## Objective

Correct the v0.7.0 Cloud Inventory Approach workspace so that users can independently:

1. type or edit the Cloud Inventory approach narrative directly;
2. map approved Cloud Inventory capabilities to formal findings or general observations; and
3. generate or enhance the narrative with AI.

The three paths may be used individually or together.

## User experience

Every operational section displays an editable **Cloud Inventory approach narrative** field. It is visible whether or not AI is enabled and whether or not capability mappings exist.

The field autosaves after the user stops typing. The save indicator reports unsaved, saving, saved, queued-offline, conflict, or failed state.

The existing actions remain available:

- **Generate with AI / Enhance with AI**
- **Version history**
- **Map approved capability**

Before AI generation begins, any unsaved manual narrative is saved so that the AI receives the latest current approach as context.

## Data and versioning

Manual narrative is stored in the existing `section_content_versions` table using:

- `content_type = CLOUD_INVENTORY_APPROACH`
- `source_type = USER`
- immutable sequential version numbers
- one current version per section/content type
- a manual-entry source reference

AI-accepted versions continue to use `source_type = AI_ACCEPTED`. Manual entry after an AI acceptance creates a new current USER version and retains the AI version in history.

No database migration is required.

## Concurrency

The client submits the expected current content version with each save. A stale save returns HTTP 409 with the current version and current text. The interface reloads rather than overwriting another contributor's change.

## Reporting

The current Cloud Inventory approach version is included in report preview, Word output, and PDF output regardless of whether it originated from manual entry or accepted AI wording.

Capability mappings remain separately governed and traceable to formal findings or general observations.

## Security and governance

- Manual entry requires existing report access.
- AI policy and approved-capability controls remain unchanged.
- Manual content changes are audited.
- Direct manual entry does not imply that a capability mapping has been approved.
