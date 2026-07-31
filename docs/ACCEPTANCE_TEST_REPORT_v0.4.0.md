# Acceptance Test Report v0.4.0

## Build identity

- Software version: 0.4.0
- Feature branch: `feature/prospect-onboarding-v0.4.0`
- Source baseline: staging v0.3.0
- Build date: 31 July 2026

## Automated results

- Pytest: 23 passed
- JavaScript syntax: passed (`node --check app/static/app.js`)
- Python compilation: passed
- OpenAPI generation: passed
- Existing Quick Entry and report workflow regression: passed

## Verified behavior

- Prospect, optional Site, and optional Engagement are created through one transactional API request.
- An Engagement created with a Site is linked to that Site.
- Post-create routing returns Sites, Engagements, or Reports according to completed records.
- Site timezone selection uses IANA identifiers and defaults from the browser.
- UK and Australian timezone fallback values are present.
- Dark header references the negative logo.
- Light login and generated outputs reference the full-colour logo.
- Service worker cache and application versions are 0.4.0.

## Staging acceptance still required

- Visual review of both logo variants at desktop and mobile breakpoints.
- Browser-timezone default behavior in target browsers.
- Manual skip-flow testing for Site and Engagement.
- Render staging deployment and user acceptance.
