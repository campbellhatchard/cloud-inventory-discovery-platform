# Acceptance Test Report — v0.8.0
## Targeted Benefits and Demo Orchestration

## Automated result

- Full pytest suite: **64 passed**
- Dedicated v0.8.0 tests: **8 passed**
- Python compilation: passed
- JavaScript syntax validation: passed
- Fresh SQLite Alembic upgrade through `e05b8c4f2d55`: passed
- OpenAPI regenerated with application version `0.8.0`

Ruff and mypy were not available in the packaging runtime. The supplied Windows installer runs the repository's complete `Deploy.ps1 -Action Validate` gate, including the pinned Ruff and mypy tools, before any commit or push is permitted.

## Acceptance coverage

1. Manual qualitative benefit retains section and approved mapping source.
2. Quantitative benefit is rejected without metric, formula, and assumptions.
3. Targeted-benefit AI snapshot contains accepted solution, approved mapping, metrics, and operational sources.
4. Selected AI benefit items become traceable PENDING benefit records.
5. Demo settings and section priorities persist and appear in the report payload.
6. Demo-plan AI snapshot includes approved benefit, approved mapping, accepted content, and priority controls.
7. Accepted demo plan is versioned and retains structured flow.
8. Demo Brief DOCX contains objectives, ordered flow, value statements, risks, and preparation guidance.

## Manual staging proving checklist

- Add a qualitative benefit from an approved capability mapping.
- Confirm the benefit enters PENDING and can be approved by a reviewer.
- Attempt a quantitative claim without a metric, formula, or assumptions and confirm it is blocked.
- Generate targeted benefits and accept only selected statements.
- Configure a section as Must Show and another as Do Not Show.
- Generate a demo plan and confirm Must Show is included and Do Not Show is absent.
- Refine and accept the plan.
- Generate a Demo Brief and download both Word and PDF.
- Confirm the document uses the accepted plan and retains v0.5.2 report formatting and footer rules.
