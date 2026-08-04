# User Guide

## Roles

### Contributor

Captures discovery notes, answers prompts, uploads evidence, records findings and metrics, and edits authorized report sections.

### Reviewer

Reviews and approves AI drafts, capability mappings, benefit statements, and supporting-evidence inclusion.

### Owner

Controls report structure, assignments, merge, validation, final publication, archive, and eligible report deletion.

### Administrator

Manages users, capabilities, knowledge, branding, audit, and retention/deletion.

## 1. Create a prospect workspace

1. Open **Prospects**.
2. Select **New prospect**.
3. Enter the prospect name, industry, and opportunity context.
4. Add one or more sites.
5. Create an engagement with survey date and objectives.
6. Add members and assign the appropriate role.

Each prospect is isolated. Do not combine unrelated customer information in one prospect workspace.

## 2. Create reports for contributors

1. Open the prospect.
2. Create a report from the standard discovery template.
3. Add report members.
4. Set the report owner.
5. Assign sections to contributors.

Multiple contributors may each have a report, or they may work in one report using section assignments. Separate reports are useful when contributors need independent field capture before consolidation.

## 3. Capture onsite observations

### Quick Entry workflow

1. Open the report. Quick Entry is the first screen.
2. Select the Area of Operation. The selection remains active for subsequent captures.
3. Select the finding type and enter the field note in the large note area.
4. Select **Capture Note**. Only the note clears; the operational area and finding type remain selected.
5. Optionally enter a caption, then select **Take Photo** to invoke the native camera or **Choose File** to attach an existing image or document.
6. Continue capturing notes and evidence. Change the Area of Operation only when the destination report section changes.

Quick Entry routes each capture immediately into the selected detailed report section. **Other** routes to General Operational Observations. The application queues notes and evidence during a transient connection loss and retains the destination section selected at capture time. Confirm the sync indicator before leaving the site.

### Strong evidence pattern

Capture:

```text
What happens now
Why it happens
Who performs it
Systems/documents used
Frequency/volume
Exception or workaround
Operational impact
Customer language
Photograph or source evidence
Open question
```

Avoid writing a solution recommendation before the current process and problem are adequately evidenced.

## 4. Complete a process assessment

For Receiving, Putaway, Transfer, Order Management, Picking, Packing, Shipping, Cycle Count Management, Work Orders, Printing, Field Inventory, and Manufacturing, use the standard structure:

1. Process purpose
2. Participants and roles
3. Trigger and inputs
4. Current process steps
5. Systems and documents
6. Inventory/data captured
7. Exceptions and workarounds
8. Volumes/frequencies/service levels
9. Controls
10. Pain points
11. Impact
12. Evidence
13. Cloud Inventory functionality
14. Proposed future process
15. Benefits
16. Assumptions/dependencies
17. Open questions
18. Confidence/evidence rating

Irrelevant sections may be removed only by the owner. A contributor can add a custom section but cannot remove standard content.

## 5. Collaborate and review

- Use **Assign** to give a section to a report member.
- Use comments for questions that must be resolved before finalization.
- Resolve comments only after the issue is addressed.
- If a save reports a version conflict, reload the current section and reconcile changes; do not overwrite another contributor blindly.

## 6. Merge reports

The owner:

1. selects the target consolidated report;
2. selects source reports from the same prospect;
3. runs merge and reviews conflicts;
4. verifies cloned evidence and findings;
5. chooses whether source reports enter the recovery/deletion lifecycle.

The target report records source lineage. Merge should not be treated as automatic editorial reconciliation.

## 7. Map Cloud Inventory capabilities

1. Create or confirm a finding.
2. Select an **approved** capability.
3. Explain why the capability addresses the finding.
4. Record prerequisites and limitations.
5. Submit for reviewer approval.

Only approved catalog capabilities can be mapped. A capability record is evidence of product functionality, not proof that it is licensed, configured, integrated, or in project scope.

## 8. Capture benefits and baselines

Benefits may be qualitative or measurable. For a measurable benefit, capture:

- baseline value;
- unit and period;
- evidence/source;
- calculation or comparison method;
- assumptions;
- confidence.

Do not state guaranteed improvement percentages without an evidenced calculation and commercial approval.

## 9. Use AI assistance

AI is available only when enabled by administrators and privacy policy. AI output remains a draft until a user accepts or a reviewer approves it.

### Fast AI Enhanced Wording

Use **AI Enhance** on Current Operations when the written discovery is ready to be professionally rewritten. The workflow is text-only and uses the section narrative, guided responses, formal findings, and relevant metrics. Photographs are human-reviewed evidence and are never sent to AI for interpretation.

1. Select **AI Enhance**.
2. The application first checks the database for an active unaccepted suggestion created from the same written sources.
3. When the source fingerprint matches, the saved wording is restored immediately and no new model request is created. This behavior is independent of elapsed time, browser, or device.
4. When no matching suggestion exists, a new draft is generated and committed before verification completes. You may close the window and return later.
5. While the draft is visible, source verification continues in the background.
6. **Accept enhanced text** becomes available only after verification passes.
7. Use **Refine** to revise the immediately preceding AI wording. The application sends the prior wording, the exact refinement request, and the current written sources. The original suggestion remains in history.
8. Use **Generate another version** only when you intentionally want an alternative draft from unchanged sources.
9. When the written sources have changed, the prior suggestion is shown as stale and cannot be refined or accepted. Select **Generate updated wording**.

Closing the AI window does not cancel the background job. Pending wording and processing status are database-backed and can be restored later.

### Photographs and AI privacy

Photographs remain normal discovery evidence for human review, captions, section placement, and report publication. The application does not send photograph pixels or image derivatives to an AI provider and does not generate AI visual interpretations or photo-to-text revisions. Human-entered photograph captions remain ordinary written evidence and may be used by text workflows where otherwise applicable.

### Speech settings

Text-to-speech uses **System / Browser Default** unless you select another voice exposed by the current browser/device. Open the account menu and select **Speech settings** to choose a voice and speaking speed or test the selection. Speech preferences are stored only on that browser/device. If a selected voice is no longer available, the application falls back to System / Browser Default.

### Other AI assistance

For Cloud Inventory Approach, targeted benefits, Executive Summary, report-quality review, and demo planning:

1. request the relevant assistance type;
2. continue working while the queued job runs;
3. review the pending suggestion;
4. verify every customer fact and capability reference;
5. approve, reject, or revise.

Approved suggestions may add narrative, capability mappings, or benefits. AI output is not authoritative and is never included automatically.

## 10. Validate and publish

### Draft

Draft validation reports warnings and errors but generation is allowed. Draft outputs display the configured `DRAFT - CONFIDENTIAL` watermark.

### Final

Final generation is blocked when mandatory content, approvals, evidence, or open issues remain. The owner may delete a genuinely non-applicable section rather than inserting placeholder text.

Available publication types:

- Full Site Discovery Report
- Solution Demonstration Brief
- Customer Follow-up Questionnaire

Download and review the final PDF before sending it to a customer. Retain the editable DOCX as the controlled source artifact.

## 11. Branding administration

Administrators can manage:

- customer/Cloud Inventory logos;
- heading/body fonts;
- primary, secondary, and accent colors;
- confidentiality statement;
- draft watermark;
- footer text.

Test both DOCX and PDF after any branding change.

## 12. Archive and retention

When an opportunity closes:

1. generate any required final output;
2. export the prospect workspace;
3. verify the ZIP;
4. archive the prospect;
5. follow the retention review process when due.

Permanent deletion is an administrator-controlled, audited action and cannot be reversed from the application.


## Guided prospect creation

Select **Create prospect** to enter the prospect, optional site, and optional engagement in one workflow. Site and engagement creation are enabled by default; clear either checkbox to skip that record. When both are entered, the engagement is linked to the new site automatically. The application then opens Sites, Engagements, or Reports according to the next incomplete step.

Site timezone defaults to the browser timezone and can be changed using the IANA timezone dropdown.
