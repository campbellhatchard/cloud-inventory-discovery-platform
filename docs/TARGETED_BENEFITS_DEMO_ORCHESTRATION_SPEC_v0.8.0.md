# Cloud Inventory Site Discovery Platform v0.8.0
## Targeted Benefits and Demo Orchestration Specification

## 1. Release objective

Version 0.8.0 completes the discovery-to-demonstration workflow by adding controlled targeted benefits and a customer-specific demonstration plan. It builds from the locked v0.7.1 baseline and preserves current operations, findings, general observations, accepted Cloud Inventory approaches, capability mappings, AI controls, document formatting, and publication history.

The intended workflow is:

1. Capture current operations, general notes, formal findings, photographs, and metrics.
2. Accept or manually enter the Cloud Inventory approach.
3. Approve capability mappings between operational sources and Cloud Inventory functionality.
4. Create targeted benefits grounded in the accepted approach and approved mappings.
5. Define internal demo priorities and constraints.
6. Generate, review, refine, and accept a presales demonstration plan.
7. Publish the accepted plan as the Demo Brief.

## 2. Targeted benefits

Each operational section provides a Targeted Benefits workspace. Users may add benefits manually or request AI generation.

Every benefit records:

- operational section;
- source reference and immutable source statement;
- category;
- qualitative or quantitative measurement type;
- formula and assumptions where applicable;
- confidence;
- approval state;
- creator, approver, and AI suggestion lineage where applicable.

Supported benefit categories are:

- Operational Efficiency
- Inventory Visibility
- Accuracy and Control
- Customer Service
- Workforce Productivity
- Compliance and Traceability
- Management Visibility
- Scalability

### 2.1 Source control

A benefit must be linked to a valid operational or solution source. Sources can include an approved capability mapping, a formal finding, a general observation, a guided response, or a recorded metric. General notes continue to be treated as Observations and do not need to be duplicated as formal findings.

### 2.2 Quantitative controls

A quantitative benefit is not accepted unless the section contains a recorded metric and the benefit includes both a measurement formula and explicit assumptions. AI is prohibited from inventing percentages, savings, time reductions, financial outcomes, or other numeric claims.

### 2.3 AI generation and review

AI-generated benefits use only:

- current operational sources;
- the accepted Cloud Inventory approach;
- approved capability mappings;
- recorded metrics;
- the user's refinement instruction.

The AI response is verified in a second pass. Unsupported claims are blocked and receive one constrained repair attempt. Users select which proposed benefit statements to accept. Accepted AI benefits enter the normal PENDING review state and require reviewer approval before appearing in controlled output.

## 3. Demo preparation inputs

The Report screen provides report-level demonstration settings:

- target audience;
- available demo duration;
- additional user priorities;
- internal preparation notes.

Each operational section provides internal demo-priority controls:

- Must Show
- Should Show
- Optional
- Do Not Show

The user may also record section-specific demo notes, known constraints, and estimated minutes. These inputs are internal and do not appear in the customer-facing Site Discovery Report.

## 4. Demo plan generation

The AI-generated demo plan uses only accepted and approved report content:

- accepted current operations and Cloud Inventory approaches;
- formal findings and general observations;
- approved capability mappings;
- approved targeted benefits;
- report-level audience and duration;
- section-level priorities, notes, constraints, and time estimates.

Must Show areas must be included. Do Not Show areas must be excluded. Each generated demo step must reference an approved capability mapping and its operational source.

The structured plan contains:

- demo objectives;
- customer operational context;
- ordered demo flow;
- functionality to demonstrate;
- scenario and preparation requirements;
- expected result;
- value statement;
- presenter talking points;
- discovery questions;
- claims and risks to avoid;
- open gaps;
- preparation notes.

The user can refine the plan with natural-language instructions before acceptance. Accepted plans are versioned. A stale plan cannot be accepted after relevant report content changes.

## 5. Demo Brief output

The Demo Brief publication consumes the current accepted Demo Plan Version and produces Word and PDF documents containing the structured plan. Existing Cloud Inventory branding, automatic table of contents, list indentation, footer logo, confidentiality statement, and R2 publication workflow are retained.

If no accepted structured plan exists, the legacy demo-brief fallback remains available, but the Report screen makes the accepted plan the primary controlled source.

## 6. Roles and governance

- Contributors can enter manual benefits and demo-priority inputs.
- Reviewers approve or reject benefits and can accept verified AI output.
- AI never automatically approves a benefit or finalizes a demo plan.
- AI prompt version, model, source snapshot, refinement instruction, verification result, reviewer action, and accepted version are retained.
- Customer-specific source information remains inside the report's access boundary.

## 7. Data model

Version 0.8.0 extends `benefits` and introduces:

- `demo_plan_settings`
- `demo_section_priorities`
- `demo_plan_versions`

Migration revision: `e05b8c4f2d55`  
Previous revision: `d94a7b3e1c44`

## 8. Exclusions

The following remain outside v0.8.0:

- Cloud Inventory MCP connectivity;
- direct writes to the Cloud Inventory platform;
- automatic numerical ROI commitments;
- automatic customer approval;
- autonomous demo execution.

Cloud Inventory MCP integration remains planned for v0.9.0.
