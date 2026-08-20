# Usability and Media Workflow Specification — v0.8.2

## Objective

Improve daily report navigation, evidence management, branding control, and document-history usability without changing the governed discovery, AI, approval, or publication model introduced through v0.8.1.

## Navigation and workspace structure

The report navigation is ordered as:

1. Quick Entry
2. Operational sections
3. Overview
4. Report
5. Demo Preparation

**Overview** contains the Executive Summary, calculated Report Quality and Readiness table, whole-report review controls, traceability, and reviewer work queue. It appears immediately above Report.

**Report** contains Report Review, validation, direct draft downloads, controlled publication, the most recent publication for each document type, and the compiled report preview.

**Demo Preparation** is a dedicated screen immediately below Report and contains report-level demo settings, section priorities, AI plan generation, accepted plan, and version history.

## Branding-controlled photograph dimensions

The default Branding profile includes:

- Unit of measure: Inches or Centimetres
- Landscape photograph maximum width and height
- Portrait photograph maximum width and height

Generated Word and PDF reports preserve image aspect ratio and fit each image within the applicable configured bounding box. Existing page-layout limits remain enforced to prevent content from exceeding the printable area.

## Prospect identity

Where a prospect logo exists, the report workspace displays it below the prospect name. Generated Full Discovery and draft report covers also place the prospect logo beneath the prospect name.

## Evidence preview and selection

Evidence responses expose both the original file and a preferred preview variant. Image cards use the normalized WEB image where available rather than a generic placeholder.

Selecting **Open file** opens an in-application modal:

- Image: responsive image preview
- PDF or text: embedded browser preview
- Other attachment: explanatory preview with an option to download the original

The inline file endpoint streams authenticated content with `Content-Disposition: inline`; standard download behavior remains available separately.

## Evidence movement and deletion

Users can select one or multiple evidence items within a section.

### Move

- Choose another active report section.
- Move all selected items in one transaction.
- Preserve original stored files and captions.
- Update cached AI photograph observations to the destination section.
- Increment source and destination section versions and the report revision.
- Record an audit event.

### Delete

- Require explicit confirmation.
- Delete every stored file variant from private object storage.
- Delete the evidence record and dependent cached AI observations.
- Increment affected section versions and report revision.
- Record an audit event.

## Context preservation

After section-level photograph upload, move, or delete, the application returns to the relevant report section and scrolls to **Site Photographs and Attachments**.

Administration retains the currently selected tab after capability, knowledge, branding, or user actions. Capability and Knowledge approval workflows no longer reset the screen to Users.

## Publication history display

Generated Documents is nested under Report Review. The interface displays only the most recent non-dismissed publication for each document type, while the database continues to retain full publication history for governance and audit purposes.

## Security and governance

- Existing report access controls apply to evidence preview, move, and delete.
- Object-storage access remains authenticated.
- No public evidence URL is introduced.
- Evidence actions are audited.
- Existing AI, R2, PostgreSQL, review, and publication controls are unchanged.
