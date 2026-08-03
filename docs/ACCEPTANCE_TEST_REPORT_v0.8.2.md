# Acceptance Test Report — v0.8.2

## Automated validation

- Full pytest suite: **79 passed**.
- Dedicated v0.8.2 usability and media tests: **6 passed**.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- Fresh Alembic migration from initial schema to `g27d0e6b4f77`: passed.
- Upgrade migration from v0.8.1 revision `f16c9d5a3e66` to v0.8.2: passed.
- OpenAPI regenerated as application version 0.8.2.

## Functional acceptance coverage

- Overview appears above Report and Demo Preparation appears below Report.
- Executive Summary and readiness governance are removed from the Report page and shown on Overview.
- Demo Preparation operates as a standalone report screen.
- Administration retains the active Capabilities or Knowledge tab after review actions.
- Branding API stores inches/centimetres and portrait/landscape dimensions.
- Photograph sizing preserves aspect ratio in both unit systems.
- Prospect logo can be placed beneath the prospect name on generated covers.
- Uploaded photographs expose and display the WEB preview variant.
- Authenticated inline image preview returns `Content-Disposition: inline`.
- Multiple evidence items can be moved to another section.
- Selected evidence can be permanently deleted and disappears from the report.
- Media actions return the user to Site Photographs and Attachments.
- Generated Documents shows the latest publication per document type under Report Review.

## Remaining deployment gate

The Windows installer runs the complete `Deploy.ps1 -Action Validate` workflow before commit or push. That workflow includes the pinned Ruff and mypy checks unavailable in the packaging runtime.
