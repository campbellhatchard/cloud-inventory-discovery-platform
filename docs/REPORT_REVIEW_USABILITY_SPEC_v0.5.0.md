# Report Review & Usability Specification — v0.5.0

## Baseline
Built from locked `baseline-v0.4.1` (`da6a026a382ce625ad5656ab4ec56c4ce3c651b7`).

## Scope
1. Add **General Discussion Points** after General Operational Observations.
2. Make every report section and discovery question optional.
3. Retire the generic question **What is the purpose and intended outcome of this section?** while retaining historical response data.
4. Add a virtual **Report** workspace at the bottom of report navigation. Sections enter the compiled review when they reach `READY_FOR_REVIEW` or `APPROVED`.
5. Move validation, publishing, and generated-document status to the Report workspace.
6. Add prospect-specific logo upload and header display.
7. Preserve report sidebar navigation position when switching sections.

## Validation behavior
Untouched optional sections and unanswered optional questions do not block final publication. A section containing captured content must reach `READY_FOR_REVIEW` or `APPROVED` before final publication. Existing governance checks for unresolved comments, pending approvals, placeholder text, evidence readiness, and merged/deleted reports remain.

## Data migration
Migration `f50a7c19d8e2` backfills the new section to active reports, removes required flags from existing rows, deactivates the retired generic purpose prompt, and adds `prospects.logo_storage_key`. Existing prompt responses remain stored.

## Storage limitation
Prospect logo upload uses the existing S3-compatible object-storage service. When staging object storage is not configured, the endpoint returns a controlled 503 rather than an unexplained application error.
