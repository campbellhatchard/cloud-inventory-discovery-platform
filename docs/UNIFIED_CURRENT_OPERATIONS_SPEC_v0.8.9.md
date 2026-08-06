# Unified Current Operations Narrative — v0.8.9

## Purpose

Remove the competing Current Operations Narrative and Findings entry/display surfaces. Each operational area has one editable written record: **Current Operations Narrative**.

## User experience

Quick Entry continues to ask for Area, Type, and Note. On capture, the note is appended directly to the selected area’s Current Operations Narrative. The selected Type is retained as a readable subheading:

- `Observation:`
- `Pain Point:`
- `Risk:`
- `Gap:`
- `Strength:`
- `Opportunity:`

The contributor may then edit, expand, reorganize, or delete any text in that narrative. The operational page no longer displays a separate Findings card or Add Finding button.

Guided discovery questions remain separate structured responses because they preserve question/answer evidence and are not duplicate free-form notes.

## Canonical data behavior

`ReportSection.narrative` is the user-facing source of truth. `Finding` rows with `source_type=NARRATIVE_DERIVED` are an internal classification index synchronized from the narrative. They exist only to preserve typed downstream behavior for readiness, AI, capability mapping, targeted benefits, and traceability.

When a narrative is edited, unchanged typed entries retain their Finding identity. Removed or changed entries are marked `SUPERSEDED`; mappings tied to superseded source wording become `STALE`. New or changed narrative entries receive new derived Finding records.

## Existing data migration

Migration `n94k7f3i1g54` revises `m83j6e2h0f43`. Existing non-rejected, section-scoped Findings are appended to the existing narrative with their classification and optional Impact, then marked `NARRATIVE_DERIVED`. Existing narrative text is preserved. Rejected or sectionless historical records remain historical.

## AI controls

Observation enhancement uses the written narrative and guided evidence without duplicating narrative-derived Finding content. AI instructions explicitly preserve user-selected classification headings and prohibit flattening, renaming, removing, or inventing classifications.

Solution and benefit intelligence use the synchronized typed index so Pain Point/Risk/Gap behavior remains structured after the UI consolidation.

## Publication

The in-app report preview and generated DOCX/PDF publish Current Operations Narrative once. They do not generate a separate Current-State Findings section from the same content.

## Acceptance criteria

1. Quick Entry appends into Current Operations Narrative in the selected operational area.
2. The selected Type is visible as the appropriate subheading.
3. The separate Findings card, Add Finding button, and finding form are absent from the operational page.
4. The complete narrative is directly editable and autosaves as before.
5. Editing a classified entry resynchronizes the internal derived index.
6. Obsolete derived entries are superseded and their mappings become stale.
7. Existing v0.8.8 Findings migrate into the narrative without deleting pre-existing narrative text.
8. AI wording instructions preserve classifications.
9. Report preview and DOCX/PDF do not duplicate narrative content as Current-State Findings.
10. All v0.8.8 platform behavior outside this controlled change remains regression-tested.
