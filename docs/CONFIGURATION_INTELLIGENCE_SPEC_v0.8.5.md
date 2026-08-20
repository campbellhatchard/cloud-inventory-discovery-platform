# Cloud Inventory Configuration Intelligence — v0.8.5

## 1. Objective

v0.8.5 converts the supplied Cloud Inventory configuration definitions into governed product knowledge that enriches Cloud Inventory functionality mapping and customer-facing **Cloud Inventory Approach** wording.

The configuration sources are **not discovery content**. They shall never create, replace, or recommend Discovery `PromptDefinition` records merely because a configuration question exists in the source.

## 2. Source basis

The initial controlled seed is derived from:

- `PSO Guided Setup v2.7 Bundle rev2 1.zip`, effective Guided Setup template version 2.7;
- `2026_07-28vBAF_v3_interview-template copy.json`, version 2.6, used as a corroborating source.

Both supplied templates contain 126 stable configuration question IDs. Their configuration definitions are materially aligned; v2.7 supplies the effective normalized structure.

## 3. Knowledge architecture

The existing capability catalog remains the high-level customer-facing product taxonomy. Detailed configuration behavior is stored underneath that taxonomy as `KnowledgeEntry` records with:

- `knowledge_kind = PRODUCT_CONFIGURATION`;
- `source_type = CONTROLLED_CONFIGURATION_REFERENCE`;
- stable source reference;
- source version;
- detailed structured source metadata;
- optional link to one high-level capability;
- global/internal classification and approval state.

Configuration records retain the source question, guidance, defined values, branching metadata, source provenance, system references, and claim-strength classification for internal traceability. The source question is not used as a discovery prompt.

## 4. High-level capability rule

Capability names and controlled descriptions must remain succinct. Configuration detail shall not be copied into the capability description.

v0.8.5 adds only the high-level capability gaps needed to organize the supplied configuration knowledge:

- `CAP-ORG-001` — Organization and Warehouse Structure
- `CAP-LOC-001` — Location and Zone Management
- `CAP-BCS-001` — Barcode and Scanning
- `CAP-INV-001` — Inventory Attribute Control
- `CAP-REQ-001` — Inventory Requests

Existing capabilities continue to organize Receiving, Putaway, Inventory Handling Units, Holds, Lot/Serial, Cycle Count, Allocation, Picking, Shipping, Returns, Replenishment, Integration, Reporting and related behavior.

## 5. Solution-intelligence behavior

When Cloud Inventory Approach generation runs, the application:

1. uses the customer-authored current-operations evidence, findings and metrics as the customer truth;
2. retrieves relevant approved high-level capabilities;
3. retrieves relevant approved configuration knowledge based on the operational content;
4. uses configuration knowledge to explain how the high-level capability may apply to the observed operation;
5. verifies the resulting product claims against the approved capability and configuration source packet.

Configuration knowledge may add product depth but may not manufacture a customer requirement or pain point.

## 6. Customer-facing guardrails

Customer-facing solution wording shall not:

- reproduce the source configuration questions as a questionnaire;
- expose `nsC7...` object or field identifiers;
- expose PS implementation actions or setup instructions;
- enumerate configuration settings unless they directly explain the observed operation;
- convert a non-standard/scope signal into a claim of standard product support.

Records identified as `SCOPE_SIGNAL_ONLY` may only support wording that specialist, integration, or scope validation is required.

## 7. Locations and Zones example

The ten Locations & Zones source definitions are normalized under `CAP-LOC-001` and related product knowledge. They establish knowledge about:

- location identification/naming;
- operational location types such as Receiving, Fixed Picking, Packing, Shipping, Replenishment and Inspection;
- zones and zone types;
- mixing restrictions;
- location capacity and dimensional/weight checks during putaway;
- bulk, rack, case, each and specialist storage areas;
- multi-item storage;
- location groups used in putaway direction.

A discovery observation such as inconsistent location identification, absence of zones, mixed storage areas or physical storage constraints can therefore retrieve these product definitions during Cloud Inventory functionality mapping without changing the discovery questionnaire.

Material-handling equipment observed onsite may be used as customer context when describing physical warehouse design. The configuration source does not establish an equipment-to-location assignment capability, so the AI must not invent one.

## 8. Administration

Administration displays configuration entries inside the Capabilities and Knowledge Repository and provides a dedicated **Import configuration pack** action.

JSON and ZIP Guided Setup sources are supported. New imports enter `PENDING` review and create zero discovery prompts. A newer approved configuration record can supersede the prior approved record while retaining its lineage.

The application-controlled v2.7/v2.6 seed is loaded as approved controlled configuration knowledge because these supplied files are the approved source basis for this release.

## 9. Data model

Alembic revision `j50g3b9e7c10` adds to `knowledge_entries`:

- `source_version`;
- `knowledge_kind`;
- `structured_data` JSON.

Existing knowledge remains valid with `knowledge_kind = GENERAL`.

## 10. Acceptance criteria

- Exactly 126 controlled configuration records are seeded from the supplied source definitions.
- All seeded records are explicitly marked `never_use_as_discovery_prompt = true`.
- No `PromptDefinition` is created from a Guided Setup question ID.
- The ten Locations & Zones records map to `CAP-LOC-001` and retain location-type, zone, mixing, capacity and specialist-storage knowledge.
- High-level capability descriptions remain concise and contain no internal system identifiers.
- A location/zoning site observation retrieves relevant configuration knowledge for Cloud Inventory Approach generation.
- Cross-dock remains a scope-validation signal and is not promoted to a standard capability.
- Configuration-pack import creates pending knowledge only and reports `discovery_prompts_created = 0`.
- Product-claim verification blocks unsupported configuration behavior and leakage of internal implementation terminology.
