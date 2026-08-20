# Section Page Simplification — v0.8.11

## Purpose

Reduce navigation and visual clutter on operational report pages while retaining governed source data and advanced capabilities behind deliberate, on-demand controls.

## Discovery Questions

- Discovery Questions are hidden by default on every operational section.
- A **Discovery Questions** button reveals the configured question wording as a read-only list.
- No textarea, answer field, photo-to-question control, response save state, or other per-question data-entry control is rendered.
- Question-panel visibility is transient UI state only. It is not stored in the database, localStorage, or sessionStorage.
- Navigating to any other report screen resets the panel to closed. Returning to the original section therefore starts closed.
- Existing historical Response records remain stored for traceability/backward compatibility; the section page no longer collects new responses.

## Demo Priority retirement

- The per-section **Demo Priority** card and form are removed from operational pages.
- The Demo Preparation screen no longer displays a per-section Operational Priorities summary.
- Overview readiness no longer displays a Demo Priority column or requires per-section demo-priority coverage.
- Historical `DemoSectionPriority` rows remain in the database and API for backward compatibility/audit; they are no longer consumed by active demo-plan generation or report-quality snapshots.
- Report-level Demo Preparation settings (audience, duration, additional guidance) remain available.

## Functional mappings

- The dedicated Approved Functionality Mappings display and the section inspector mapping card are removed from operational pages.
- Capability mappings remain governed database records and remain available to solution intelligence, targeted benefits, traceability, report output, reviewer queues, and demo orchestration.
- Existing mapping creation/generation capabilities remain available; this release changes display, not the underlying mapping model.

## AI History

- The persistent AI Assistance inspector card is removed.
- An **AI History** button appears alongside the section AI controls.
- AI History is hidden by default and shows recent section-level Current Operations enhancement, Cloud Inventory Approach, and Targeted Benefits AI events when revealed.
- Each entry displays generation time, review state, and stored generated content. Pending entries expose review actions when the current user's access scope permits review.
- AI History visibility is transient UI state and resets closed whenever navigation moves to another report screen.
- The compact AI Enhance status (`Not Run`, `Not Reviewed`, `Accepted`) remains visible beneath AI Enhance at all times.

## Data retention and schema

No schema migration is introduced. Existing discovery responses, Demo Priority rows, mappings, AI suggestions, and audit history are retained. v0.8.11 changes active collection/display and removes hidden Demo Priority influence; it does not destructively delete historical records.
