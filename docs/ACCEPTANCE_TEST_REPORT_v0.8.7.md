# Acceptance Test Report — v0.8.7

## Automated validation

- Full pytest regression suite: **105 passed**.
- Dedicated v0.8.7 user-lifecycle/role-administration tests: **6 passed**.
- Python compilation: passed.
- JavaScript syntax validation: passed.
- OpenAPI generation: passed as application version **0.8.7**.
- Fresh Alembic migration through `l72i5d1g9e32`: passed.
- Upgrade migration from v0.8.6 `k61h4c0f8d21` to `l72i5d1g9e32`: passed.

## Functional acceptance coverage

- Administrator can change global user roles.
- At least one role is required.
- Administrator cannot remove ADMIN from their own account.
- Last active Administrator protections remain enforced.
- Delete User API/UI is removed.
- Administrator can change user status between ACTIVE and INACTIVE.
- Deactivation revokes active sessions immediately.
- Deactivation preserves roles and prospect memberships.
- Inactive users cannot authenticate.
- Inactive users remain visible in Administration.
- Inactive users are excluded from normal collaboration/assignment selectors.
- Reactivation restores authentication eligibility using the existing identity/password.
- Deactivating an owner with owned work requires an active Owner/Admin replacement.
- Ownership and section assignments transfer to the selected replacement.
- Migration converts legacy `DELETED` user rows to `INACTIVE`.
- v0.8.6 password reset, photograph-AI retirement, speech preferences, configuration intelligence, and reporting regressions remain passing.

## Packaging-runtime limitation

The packaging runtime does not contain the repository-pinned Ruff and mypy binaries. The Windows `Deploy.ps1 -Action Validate` gate remains mandatory before commit/push and will execute those static checks together with the complete deployment validation.
## Windows validation correction R1

The first Windows `Deploy.ps1 -Action Validate` attempt stopped before commit/push because Ruff reported one unused import in the retained v0.8.6 regression test: `from sqlalchemy import select` in `tests/test_user_admin_photo_retirement_speech_v086.py`. The import was removed with no application behavior change. The corrected source retains version 0.8.7 because the failed attempt was never committed or promoted.

Post-correction validation in the packaging environment: **105 tests passed**, Python compilation passed, JavaScript syntax passed, OpenAPI 0.8.7 contract checks passed, fresh Alembic migration reached `l72i5d1g9e32`, and upgrade from v0.8.6 `k61h4c0f8d21` reached `l72i5d1g9e32`. The corrected Windows installer reruns the repository's authoritative Ruff/mypy gate before commit or push.

