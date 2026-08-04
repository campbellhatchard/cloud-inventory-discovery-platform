# Deployment Guide — v0.8.7

## Baseline

- Locked application baseline: v0.8.6
- Exact baseline commit: `4aaa7369de80e69e9f297c1dbc9be1705eacbfe6`
- Baseline database revision: `k61h4c0f8d21`
- v0.8.7 database revision: `l72i5d1g9e32`
- Feature branch: `feature/user-lifecycle-role-admin-v0.8.7`

## Environment

No new Render secrets or environment variables are introduced. Keep the existing v0.8.6 Web-service `DEFAULT_USER_TEMP_PASSWORD` secret configured.

## Controlled deployment

1. Place the v0.8.7 implementation package and PowerShell installer directly in Downloads; do not extract the package.
2. Run the installer with `-PromoteToStaging`.
3. The installer verifies that `origin/staging` still equals the exact locked v0.8.6 commit before applying any source.
4. The installer runs the complete Windows staging validation gate before commit or push.
5. Sync the Render Blueprint if required.
6. Deploy Web first. Alembic upgrades `k61h4c0f8d21` to `l72i5d1g9e32` and converts legacy user status `DELETED` to `INACTIVE`.
7. Confirm Web reports application version 0.8.7 and is healthy.
8. Deploy Worker and confirm version 0.8.7.
9. Smoke-test Edit roles, Deactivate, Activate, Reset password, and active-only collaboration selectors.

## Lifecycle smoke test

- Create a Contributor.
- Change roles to Contributor + Reviewer.
- Deactivate the user and confirm login is rejected.
- Confirm roles remain visible in Administration.
- Confirm the inactive user is absent from normal assignment selectors.
- Reactivate the user and confirm login is possible again.
- Confirm Delete User is no longer available.
## Corrected installer retry behavior

Use the `CORRECTED-R1` installer after the initial Ruff F401 failure. It always refreshes the archived v0.8.7 source from the newest corrected implementation package. If and only if the local repository is on `feature/user-lifecycle-role-admin-v0.8.7`, HEAD is the locked v0.8.6 baseline `4aaa7369de80e69e9f297c1dbc9be1705eacbfe6`, and the working tree is dirty, the installer treats this as the known failed-validation state. It backs up tracked changes and untracked files under the v0.8.7 installer recovery folder, resets to verified `origin/staging`, cleans untracked files, reapplies the corrected source, and runs full validation. Any other dirty state is refused without reset.

