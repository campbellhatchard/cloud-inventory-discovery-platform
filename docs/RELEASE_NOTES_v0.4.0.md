# Release Notes v0.4.0

## Added

- Guided creation of Prospect, optional Site, and optional Engagement records.
- Atomic `/api/prospects/onboard` endpoint.
- Post-create routing based on which records were created.
- IANA timezone dropdowns with browser timezone defaults.
- Explicit full-colour and negative Cloud Inventory logo assets.

## Changed

- The dark application header now uses the supplied negative logo directly.
- The light login card, favicon, PWA manifest, and generated documents use the supplied full-colour logo.
- The Site modal no longer accepts unrestricted timezone text.

## Compatibility

- No database migration is required.
- Existing Prospects, Sites, Engagements, Reports, and generated publications are unchanged.
- Existing custom report logos remain supported.
