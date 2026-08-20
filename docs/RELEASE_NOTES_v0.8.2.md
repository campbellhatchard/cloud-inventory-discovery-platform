# Release Notes — v0.8.2

## Usability and Media Workflow

### Added

- Dedicated **Overview** page above Report for Executive Summary, Report Quality and Readiness, traceability, and reviewer work queue.
- Dedicated **Demo Preparation** page below Report.
- Branding controls for landscape and portrait report-photo width and height, selectable in inches or centimetres.
- Prospect logo beneath the prospect name in the report workspace and generated report cover.
- Normalized image previews on evidence cards.
- Authenticated in-application preview for images, PDFs, and text files.
- Multi-select evidence movement between report sections.
- Multi-select evidence deletion with confirmation, object-storage cleanup, version updates, and audit logging.
- Context return to Site Photographs and Attachments after upload, move, or delete.

### Changed

- Administration retains the current tab after capability, knowledge, branding, and user actions.
- Report readiness table uses a compact fixed layout on desktop so fields fit across the page.
- Generated Documents now appears within Report Review.
- Only the newest non-dismissed publication for each document type is displayed.
- Report evidence payloads distinguish the original file from the preferred preview variant.
- Inline file requests stream in the browser rather than initiating a download.
- Application, package, Blueprint, OpenAPI, service-worker, and test versions updated to 0.8.2.

### Database

Alembic revision: `g27d0e6b4f77_usability_photo_workflow.py`.

The migration adds photograph sizing fields to the default Branding profile. Existing profiles receive the current default dimensions.

### Environment impact

No new environment variables are required. Existing PostgreSQL, R2, OpenAI, LibreOffice, Web, and Worker configuration is reused.
