# Release Notes - v0.5.2

## Report Output Formatting & Publication History

v0.5.2 improves generated Word/PDF presentation and makes historical publication failures easier to distinguish from current publication state.

### Added
- Real Word Table of Contents field using Heading 1-3 references and the Automatic Table 2 pattern.
- LibreOffice UNO field-refresh helper so generated DOCX/PDF files contain refreshed TOC page numbers in Render.
- Small full-colour Cloud Inventory footer logo on pages after page 1.
- Exact proprietary/confidentiality footer notice on pages after page 1.
- Publication revision and date/time in Generated Documents.
- `PREVIOUS FAILED ATTEMPT` treatment for superseded failures.
- Non-destructive `Dismiss failed attempt` action.
- Alembic migration `b72e1f8c5d21`.

### Changed
- Bullet and numbered-list output now uses explicit indented Word list styles.
- Page 1 is isolated in a footer-free cover section.
- Removed the legacy `Cloud Inventory | Confidential` footer label.
- Direct Draft Word/PDF and controlled publications both refresh the TOC on the Render/Linux generation path.
- Docker image now installs `python3-uno` in addition to LibreOffice Writer.

### Preserved
- v0.5.1 collaborative section capture.
- Report-level Draft / Ready for review / Finalized workflow.
- Direct draft downloads independent of persistent R2 storage.
- Cloudflare R2 controlled-publication storage.
