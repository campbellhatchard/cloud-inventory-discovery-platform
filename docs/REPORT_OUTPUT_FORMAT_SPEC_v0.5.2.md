# Report Output Formatting Specification - v0.5.2

## Release objective
Improve generated Cloud Inventory report presentation and navigation while preserving the collaborative v0.5.1 capture model and Cloudflare R2 publication workflow. This release also incorporates the deferred Generated Documents usability enhancement for historical publication failures.

## Functional changes

### Indented bullets and numbered lists
- Generated bullet paragraphs use the Word `List Bullet` style with an explicit 0.35 inch left indent and 0.18 inch hanging indent.
- Numbered narrative lines beginning with `1.` or `1)` are converted to the Word `List Number` style using the same explicit indentation.
- Existing generated finding, capability, benefit, evidence, and follow-up-question lists inherit the same indented list styles.

### Automatic Table of Contents
- Replace the static Table of Contents list with a real Word TOC field.
- Use the Word Automatic Table 2 pattern: built-in `TOC Heading` plus a `TOC` field over Heading levels 1-3 with hyperlinks and page references.
- Mark document fields for update when opened in Word.
- On the Render/Linux generation path, refresh the TOC through LibreOffice UNO before returning or storing DOCX/PDF output so page numbers and dot leaders are populated in generated files.
- Add `python3-uno` to the Render Docker image for deterministic field refresh.

### Footer after the cover page
- Page 1 has no footer.
- The cover is isolated in its own Word section to keep the first page footer-free across both Microsoft Word and LibreOffice field-refresh processing.
- Every page after page 1 contains:
  - a small full-colour Cloud Inventory logo at bottom left;
  - the proprietary/confidentiality notice in the footer;
  - the page number at bottom right.
- Remove the former `Cloud Inventory | Confidential` footer label.

The exact footer text is:

> This document is the property of and proprietary to Cloud Inventory and contains trade secret and confidential information, and is solely for the Customer's internal use. Without the express written consent of Cloud Inventory, this document shall not be used, reproduced, copied, disclosed, or transmitted, in whole or in part. Copyright Cloud Inventory. All rights reserved.

### Generated Documents history
- Display report revision and publication date/time for each generated-document attempt.
- When a failed attempt is followed by a successful publication of the same type, label the older entry `PREVIOUS FAILED ATTEMPT`.
- Reviewers can dismiss a failed attempt from the active Generated Documents list.
- Dismissal is non-destructive: the Publication row remains in the database and the action is captured in audit history.

## Migration
Revision `b72e1f8c5d21`:
- adds nullable `publications.dismissed_at`;
- adds nullable `publications.dismissed_by` with `SET NULL` foreign key behavior;
- replaces the legacy branding footer text only where it exactly equals `Cloud Inventory | Confidential`;
- preserves all existing publication and audit records.

## Backward compatibility
- No discovery/report content is removed.
- v0.5.1 collaborative capture, report-level status, direct draft downloads, and Cloudflare R2 publication behavior remain unchanged.
- Existing failed publication records remain available for audit even when dismissed from the UI.
