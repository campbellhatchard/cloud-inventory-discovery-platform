# Cloud Inventory Solution Intelligence Specification - v0.7.0

## Purpose

v0.7.0 adds the second AI-assisted content layer to each operational discovery section: a governed **Cloud Inventory Approach** that explains how approved Cloud Inventory functionality can support the operation captured during discovery.

The release also changes capability mapping so ordinary current-operations notes are usable as **Observations** even when a contributor did not create a formal Finding record.

## Functional scope

### 1. General notes are mapping Observations

For Cloud Inventory functionality assessment and mapping, the following section content is treated as an Observation source:

- the current-operations narrative;
- non-empty guided-discovery responses;
- explicit Findings, preserving their recorded type such as Observation, Pain Point, Risk, Gap, Strength, or Opportunity.

General notes are not silently converted into Finding database records. Their original form and wording are preserved. They become first-class mapping sources through source references such as `section:narrative` and `response:<id>`.

### 2. Source-aware capability mappings

Capability mappings may point to either:

- an explicit Finding; or
- a general Observation source from the section narrative or guided response.

Each mapping stores a source snapshot containing the source reference, source type, label, and statement used when the mapping was created. This keeps the rationale auditable if the operational narrative is later edited.

Only APPROVED Cloud Inventory capabilities may be mapped.

### 3. Cloud Inventory Approach

Each operational section receives a separate Cloud Inventory Approach card. Users can:

- generate an AI proposal;
- compare the current accepted approach with the proposed approach;
- see the operational observations and approved capabilities used to ground the response;
- refine the proposed wording using natural-language instructions;
- use browser text-to-speech to hear the proposal;
- accept a verified proposal when they have reviewer authority;
- review prior accepted solution versions;
- manually map approved capabilities to operational sources.

Accepted solution content is stored as `SectionContentVersion` with content type `CLOUD_INVENTORY_APPROACH`. It does not overwrite the current-operations narrative.

### 4. AI grounding and claim control

Solution generation uses only:

- current operational sources from the selected section;
- section metrics;
- approved Cloud Inventory capabilities relevant to the operational module;
- approved historical knowledge available to the current prospect or explicitly approved for cross-prospect reuse;
- the previously accepted Cloud Inventory Approach, when present;
- the user's refinement instruction.

The prompt explicitly treats uncategorized current-operations notes as Observations but prohibits the model from manufacturing a Pain Point or other stronger classification from neutral source material.

The AI may not invent:

- product functionality;
- integration behavior;
- configuration behavior;
- implementation commitments;
- performance improvements or financial results;
- guarantees;
- customer facts not present in source observations.

A second product-claim verification pass checks the proposed narrative against the approved source packet. A blocked proposal receives one constrained repair attempt. Only a PASSED proposal containing valid capability-to-observation mappings can be accepted.

### 5. Stale-source protection

An accepted AI proposal must still match the section version, capability versions/statuses, and approved knowledge versions used at generation time. If operational content, a capability, or knowledge changes after generation, acceptance is rejected and the proposal must be regenerated.

### 6. Historical Cloud Inventory knowledge

Administration receives an historical-document import workflow. Supported document types use the application's existing extraction service and are split into reviewable knowledge chunks.

Imported historical knowledge is:

- PENDING by default;
- never automatically reusable across prospects;
- optionally tied to an operational module and approved capability;
- prospect-specific and confidential when imported against a prospect;
- unavailable to AI solution generation until explicitly approved.

Existing governance remains in force: prospect-specific knowledge must be de-identified and reviewed before it may become reusable across prospects.

### 7. Report output

Accepted Cloud Inventory Approach text is included in draft and controlled report output. Approved mappings are listed with their operational source so the customer-facing solution explanation remains traceable to observed conditions.

## Data model changes

Migration `d94a7b3e1c44` extends `capability_mappings` with:

- nullable `finding_id`;
- `section_id`;
- `source_ref`;
- `source_type`;
- `source_label`;
- `source_statement`;
- `ai_suggestion_id`.

Existing finding-based mappings are backfilled to the new source-aware form.

## Deliberate exclusions

v0.7.0 does not include:

- AI-generated targeted Benefits; planned for v0.8.0;
- Demo Preparation orchestration; planned for v0.8.0;
- Cloud Inventory MCP connectivity; planned for v0.9.0;
- automatic approval of capabilities or imported historical knowledge;
- automatic conversion of general notes into formal Findings.
