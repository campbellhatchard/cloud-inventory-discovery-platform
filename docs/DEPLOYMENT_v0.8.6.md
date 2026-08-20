# Deployment Guide — v0.8.6

## Locked baseline

- Base branch: `staging`
- Expected application: `0.8.5`
- Exact baseline commit: `a8eea8336863d48e9beb3ed938846965bb942b42`
- Required base migration: `j50g3b9e7c10`
- New migration: `k61h4c0f8d21`
- Feature branch: `feature/user-admin-evidence-privacy-speech-v0.8.6`

The installer refuses to apply the release to any different staging commit or to a dirty local repository.

## New environment secret

The web service requires `DEFAULT_USER_TEMP_PASSWORD`. Supply the approved temporary-password value through Render/environment secrets before starting the v0.8.6 web application. Do not commit the value to GitHub or deployment files. The worker does not require this value.

## Deployment sequence

1. Place the v0.8.6 implementation package and PowerShell installer directly in Downloads; do not extract the package.
2. In the same PowerShell process, set process-scoped execution policy to Bypass and invoke the installer with `-PromoteToStaging`.
3. The installer validates the exact staging baseline, creates the feature branch, applies source, and runs `Deploy.ps1 -Action Validate -Environment staging -Region ohio` before any commit or push.
4. Sync the Render Blueprint and confirm the new web-service secret is configured.
5. Deploy Web first so Alembic upgrades to `k61h4c0f8d21` and removes the legacy photo-AI cache table.
6. Confirm Web reports application version 0.8.6 and login/user administration works.
7. Deploy Worker and confirm worker version 0.8.6.
8. Complete staging smoke tests for reset/delete user, first-login password change, photo upload without AI analysis, text AI, and speech preferences.
