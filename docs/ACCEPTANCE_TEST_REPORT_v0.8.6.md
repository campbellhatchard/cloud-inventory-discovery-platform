# Acceptance Test Report — v0.8.6

## Automated validation completed in the packaging environment

- Full Python test suite: **99 passed**.
- Dedicated v0.8.6 user-administration/photo-retirement/speech tests plus retained fast-text regression: **8 passed**.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- OpenAPI generation: passed; version 0.8.6, reset/delete user endpoints present, photo-analysis endpoint absent.
- Fresh Alembic migration through `k61h4c0f8d21`: passed.
- Upgrade migration from v0.8.5 `j50g3b9e7c10` to `k61h4c0f8d21`: passed.

## Functional acceptance coverage

- Password minimum is 10 characters with complexity retained.
- New users can receive the deployment-configured temporary password and are forced to change it before prospect access.
- Admin reset revokes target sessions, clears lockout state, and forces a password change.
- User deletion is a controlled soft delete preserving historical attribution while removing active access.
- Owned reports/engagements require a valid replacement owner; ownership and prospect membership are reassigned.
- Photograph upload remains available as human-reviewed evidence.
- Current application source has no photo-analysis API, worker lane, image-AI payload, or photo-context request purpose.
- Text AI remains photo-free and rejects supplied photograph evidence IDs.
- System / Browser Default is the speech default; device-exposed voices and rate preferences are locally selectable.
- v0.8.4 durable wording restoration/regeneration/refinement regression tests continue to pass.
- v0.8.5 Configuration Intelligence regression tests continue to pass.

## Windows deployment gate

The packaging environment does not contain the pinned Ruff and mypy executables and cannot install them from the network. The standard Windows `Deploy.ps1 -Action Validate` step remains a mandatory pre-commit gate and will run Ruff, mypy, the test suite, deployment/security checks, and document-generation validation before the installer can commit or push v0.8.6.
