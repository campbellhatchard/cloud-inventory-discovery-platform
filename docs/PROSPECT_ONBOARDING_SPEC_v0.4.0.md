# Prospect Onboarding and Branding Enhancement Specification

**Software version:** 0.4.0  
**Baseline:** staging v0.3.0  
**Feature branch:** `feature/prospect-onboarding-v0.4.0`

## Scope

This enhancement improves first-use navigation when a prospect is created and standardizes Cloud Inventory logo selection by background context.

## Guided prospect creation

The Create Prospect workflow captures mandatory prospect details and offers optional Site and Engagement sections. Both optional sections are enabled by default and can be skipped independently. The backend creates all selected records in one transaction.

Post-create routing is:

- Prospect only: Sites tab
- Prospect and Site: Engagements tab
- Any created Engagement: Reports tab

When both a Site and Engagement are entered, the Engagement is automatically linked to the newly created Site.

## Timezones

Site timezone fields use an IANA timezone dropdown. The browser timezone is selected by default through `Intl.DateTimeFormat().resolvedOptions().timeZone`. Modern browsers use the complete `Intl.supportedValuesOf('timeZone')` list; a fallback list includes United States, Canadian, Australian, New Zealand, UTC, and UK Crown Dependency timezones. UK coverage includes `Europe/London`, `Europe/Guernsey`, `Europe/Isle_of_Man`, and `Europe/Jersey`.

## Branding

- Dark application header: negative Cloud Inventory logo
- Light login card and light user interface surfaces: full-colour logo
- Generated DOCX and PDF output: full-colour logo by default
- Custom report logos continue to override the standard output logo
- Favicon and PWA manifest: full-colour logo

## Acceptance criteria

1. Create Prospect offers Prospect, Site, and Engagement details in one guided flow.
2. Site and Engagement can each be skipped.
3. Selected records are created atomically.
4. New Engagement links to the newly created Site.
5. Landing tab follows the routing rules above.
6. Site forms use an IANA timezone dropdown.
7. Browser timezone is selected by default.
8. UK and Australian timezones are available.
9. Header uses the negative logo without CSS colour inversion.
10. Login and generated documents use the full-colour logo.
