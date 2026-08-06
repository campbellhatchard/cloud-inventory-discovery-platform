# Deployment Guide — v0.8.9

## Locked baseline

- Application: v0.8.8
- Exact staging commit: `5e1a7da75d5c3b0b9128ded67ee4c86ce02deaac`
- Baseline migration: `m83j6e2h0f43`
- v0.8.9 migration: `n94k7f3i1g54`
- Feature branch: `feature/unified-current-operations-v0.8.9`

## Deployment order

1. Place the v0.8.9 implementation ZIP and PowerShell installer directly in Downloads; do not extract the ZIP.
2. Run the installer with `-PromoteToStaging`.
3. The installer verifies the exact v0.8.8 staging SHA and runs the complete Windows validation gate before commit or push.
4. Deploy Render **Web first** so `n94k7f3i1g54` consolidates existing non-rejected section Findings into Current Operations Narrative.
5. Confirm `/readyz` is healthy and application version is 0.8.9.
6. Open Receiving/Putaway/Picking and confirm there is one Current Operations Narrative and no separate Findings card.
7. Capture Quick Entry notes using at least Observation and Pain Point and confirm both appear in the destination narrative with their subheadings.
8. Edit the narrative and confirm the edit persists.
9. Deploy Worker after Web is healthy.

No new Render environment variables are required.
