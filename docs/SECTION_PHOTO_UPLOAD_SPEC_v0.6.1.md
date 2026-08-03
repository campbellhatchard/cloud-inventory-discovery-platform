# Section Photo Upload Specification - v0.6.1

## Objective

Restore the ability to add site photographs directly while working inside an operational report section, without requiring the user to leave the section and route the image through Quick Entry.

## Functional behavior

Every active operational section displays an **Add photographs** control in the Site photographs and attachments card. PHOTO-type discovery prompts display **Add photo to this section**.

Selecting either control opens a modal scoped to the current section. The user can select one or more image files and optionally enter a caption/observation. The same caption is applied to each photograph selected in that upload action.

Direct section photographs are stored using the existing evidence API with:

- `section_id`: current operational section
- `placement`: `INLINE`
- `classification`: `CONFIDENTIAL`
- `evidence_type`: derived by the server as `PHOTO`

The existing evidence review controls remain responsible for changing an item to Supporting only.

## Offline behavior

When offline, selected photographs are written to the existing IndexedDB evidence queue with the current report and section identifiers. They are uploaded through the existing evidence endpoint when synchronization resumes.

## Relationship to AI Observation Enhancement

Directly uploaded photographs become ordinary section evidence and therefore appear in the v0.6.x photograph selection list used by AI Observation Enhancement. No separate AI ingestion path is introduced.

## Non-goals

- No database migration.
- No change to Quick Entry.
- No attachment/document upload from the section-level modal; this hotfix is specifically for photographs.
- No automatic AI analysis at upload time. Analysis remains user-requested through AI Enhance.
