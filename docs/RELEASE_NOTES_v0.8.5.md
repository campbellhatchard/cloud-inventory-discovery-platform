# Release Notes — v0.8.5

## Cloud Inventory Configuration Intelligence

v0.8.5 builds on the v0.8.4 durable AI wording baseline and adds a governed product/configuration knowledge layer derived from the supplied Cloud Inventory Guided Setup sources.

### New functionality

- Added 126 controlled `PRODUCT_CONFIGURATION` knowledge records from Guided Setup v2.7, corroborated by the supplied v2.6 template.
- Added high-level, succinct capability records for Organization and Warehouse Structure, Location and Zone Management, Barcode and Scanning, Inventory Attribute Control, and Inventory Requests.
- Added structured source version, source-question metadata, configuration values, product/system references and claim-strength metadata to knowledge records.
- Added a JSON/ZIP Configuration Knowledge importer in Administration.
- Added configuration-aware relevance scoring to Cloud Inventory Approach generation.
- Added explicit AI rules preventing configuration sources from becoming discovery questions.
- Added customer-facing controls preventing internal `nsC7` identifiers, PS setup actions and exhaustive settings lists from leaking into solution narrative.
- Added `SCOPE_SIGNAL_ONLY` handling so non-standard configuration topics can trigger validation without being presented as standard product support.

### Discovery behavior

No Guided Setup configuration definition is added to the Discovery Question Library. The existing expert-led discovery prompts and Quick Entry workflows are unchanged.

### Locations & Zones

Location and Zone Management can now be explained using controlled knowledge for location types, zones, mixing rules, capacity checks, specialist storage and location groups when those subjects are relevant to observed customer operations.

### Database

Alembic revision `j50g3b9e7c10` adds `source_version`, `knowledge_kind` and `structured_data` to `knowledge_entries`.

### Environment impact

No new environment variables are required. Existing database, OpenAI, R2 and worker configuration is reused.
