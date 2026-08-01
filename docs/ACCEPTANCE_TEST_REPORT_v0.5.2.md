# Acceptance Test Report - v0.5.2

## Build
Cloud Inventory Site Discovery Platform v0.5.2 - Report Output Formatting & Publication History.

## Automated validation performed in build environment
- Pytest: **37 passed**.
- JavaScript syntax: `node --check app/static/app.js` passed.
- Python compilation: `compileall` passed for application, scripts, and Alembic sources.
- Alembic clean-database upgrade: passed through revision `b72e1f8c5d21`.
- OpenAPI document regenerated at application version `0.5.2`.

## Generated-document QA
A representative Full Discovery draft was generated, refreshed through LibreOffice UNO, and rendered as both DOCX and PDF. Every rendered page was visually inspected.

Verified:
- page 1 has no footer;
- pages after page 1 contain the small full-colour Cloud Inventory logo, exact proprietary notice, and page number;
- the former `Cloud Inventory | Confidential` footer text is absent;
- the Table of Contents is populated from a real TOC field with dot leaders and page references;
- bullet points and numbered points are visibly indented;
- no footer clipping, overlapping content, or broken page layout was observed in the QA sample.

## Functional acceptance coverage
- Failed publication attempts can be dismissed without deleting the Publication database record.
- Dismissal metadata records the user and timestamp.
- Dismissed failures are excluded from the active report publication list.
- Generated Documents includes report revision and generated/completed time.
- Superseded failures can be presented as `PREVIOUS FAILED ATTEMPT`.

## Deployment gate
The Windows installer runs the repository's complete `Deploy.ps1 -Action Validate -Environment staging -Region ohio` validation before creating a Git commit or pushing to GitHub. This standard repository validation includes Ruff and the project deployment checks. If that validation fails, the installer stops before commit/push.

Ruff is intentionally not claimed as locally executed in the package-build container because Ruff is not installed in that container environment; it remains an enforced Windows deployment gate.
