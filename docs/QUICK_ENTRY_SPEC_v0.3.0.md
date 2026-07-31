# Quick Entry Enhancement Specification — v0.3.0

## 1. Purpose

Quick Entry is the primary field-capture screen for a discovery report. It appears before Opportunity Overview in report navigation but is not a report section and is excluded from validation and generated DOCX/PDF publications.

## 2. Field workflow

Quick Entry contains only:

1. Area of operation.
2. Quick Field Capture.
3. Photographs and Attachments.

The selected area remains selected after each capture and is persisted per report in browser local storage.

## 3. Area routing

| Quick Entry value | Destination report section |
| --- | --- |
| Receiving | Receiving |
| Putaway | Putaway |
| Transfer | Transfer |
| Order Management | Order Management |
| Picking | Picking |
| Packing | Packing |
| Shipping | Shipping |
| Cycle Count | Cycle Count Management |
| Work Orders | Work Orders |
| Printing | Printing |
| Other | General Operational Observations |

The destination section ID is resolved before each capture and stored with offline queue items so later dropdown changes cannot redirect queued evidence.

## 4. Note capture

The user selects a finding type and enters a note in a large multiline field. On successful capture:

- The note is created as a normal Finding in the selected report section.
- The note field clears.
- Area and finding type remain selected.
- The destination section moves from `NOT_STARTED` to `IN_PROGRESS`.

Supported finding types are Observation, Pain Point, Risk, Gap, Strength, and Opportunity.

## 5. Photograph and attachment capture

Quick Entry provides two explicit actions:

- **Take Photo** uses an image-only file control with `capture="environment"` so supported phones and tablets invoke the native rear-facing camera.
- **Choose File** supports images, PDF, DOCX, XLSX, CSV, TXT, Markdown, JSON, and XML files.

Caption is optional. Placement is not exposed to the user; Quick Entry evidence is stored as `INLINE` against the selected report section. Existing private storage, image normalization, extraction, classification, and audit controls remain applicable.

## 6. Detailed report sections

Detailed sections no longer contain competing quick-note and upload forms. They continue to show:

- Section narrative and guided prompts.
- Findings routed from Quick Entry.
- Evidence routed from Quick Entry.
- Detailed finding creation.
- Evidence review and publication disposition.
- Collaboration, capability mapping, benefits, AI review, validation, and publication controls.

Photo prompts link back to Quick Entry.

## 7. Printing process

v0.3.0 adds a standard Printing section and `PRINTING` process module immediately after Work Orders. It uses the standard 18 process prompts. Migration `e3b7c1a9d2f4`:

- Adds Printing to full-discovery templates.
- Adds Printing prompts.
- Backfills Printing into all non-finalized, non-deleted reports.
- Preserves finalized reports without modification.

## 8. Offline operation

Notes continue to use the existing IndexedDB mutation queue. Photos and attachments continue to use the evidence queue. Each queued item stores its resolved section ID.

## 9. Acceptance criteria

- Opening a report without a section route displays Quick Entry.
- Quick Entry precedes Opportunity Overview in desktop and mobile navigation.
- Quick Entry is excluded from report publications and final validation.
- Multiple notes can be entered without reselecting the operational area.
- Camera and file selection are separate actions.
- Caption is optional and placement is not shown.
- Each capture appears in the selected detailed report section.
- Other routes to General Operational Observations.
- Printing routes to the new Printing section.
- Evidence-only capture sets the destination section to In Progress.
- Offline queued captures retain the destination section selected at capture time.
- Finalized reports are not modified by the migration.
