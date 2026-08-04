# Deployment Guide — v0.8.5

## Locked baseline

- Base branch: `staging`
- Required application version: `0.8.4`
- Required staging commit: `fe0f5c14c11e2556f0a489e3e7b0aaff97e72ab9`
- Required migration: `i49f2a8d6b99_ai_wording_persistence.py`
- Target feature branch: `feature/configuration-intelligence-v0.8.5`
- New migration: `j50g3b9e7c10_configuration_intelligence.py`

The installer refuses to apply v0.8.5 to any other staging commit.

## Downloads deployment sequence

Place these two files directly in the Windows Downloads folder:

- `Cloud_Inventory_Discovery_Platform_v0.8.5_Implementation_Package.zip`
- `Apply_Configuration_Intelligence_v0.8.5_From_Downloads.ps1`

Do not extract the implementation package.

Open Windows PowerShell and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

& "$env:USERPROFILE\Downloads\Apply_Configuration_Intelligence_v0.8.5_From_Downloads.ps1" `
    -PromoteToStaging
```

The process-scoped execution-policy change ends when that PowerShell process closes.

## Installer behavior

The installer follows the established Discovery Reports deployment pattern:

1. resolves Downloads, repository and installer paths from `%USERPROFILE%`;
2. moves v0.8.5 release files into `CloudInventoryDiscovery\installers\v0.8.5-configuration-intelligence`;
3. canonicalizes browser duplicate suffixes such as `(1)`;
4. extracts the implementation package when the standalone source ZIP is not present;
5. validates the source ZIP SHA-256 when the manifest is present;
6. refuses a dirty local repository;
7. fetches GitHub and verifies the exact locked v0.8.4 staging commit, application version and migration;
8. creates `feature/configuration-intelligence-v0.8.5` from that verified staging commit;
9. applies the source while excluding Git/runtime/secrets/local databases;
10. runs `Deploy.ps1 -Action Validate -Environment staging -Region ohio`;
11. commits and pushes only when validation succeeds;
12. with `-PromoteToStaging`, fast-forwards and pushes `staging` only after the feature branch validates.

## Render deployment

After the GitHub staging promotion succeeds:

1. Sync the Render Blueprint.
2. Deploy the Web service first.
3. Confirm Alembic upgrades to `j50g3b9e7c10`.
4. Confirm the application reports `APP_VERSION=0.8.5`.
5. Deploy the Worker service from the same staging commit.
6. Confirm the worker heartbeat reports v0.8.5.

No new environment variables are required.

## Staging smoke test

1. Open Administration → Capabilities and confirm the new high-level capabilities remain concise.
2. Open Administration → Knowledge and confirm controlled configuration records are labeled **Configuration**.
3. Confirm source version 2.7 configuration records are approved and reusable internally.
4. Confirm the Discovery Question Library contains no Guided Setup `gs-*` prompts.
5. In a report Putaway section, enter an observation describing missing location identification/zoning and mixed physical storage constraints.
6. Generate the Cloud Inventory Approach.
7. Confirm the response can explain relevant location types, zoning, capacity or storage controls where applicable, but does not expose `nsC7` identifiers, source questions or PS setup instructions.
8. Confirm material-handling equipment context does not cause the application to invent an equipment-to-location configuration capability.
9. Confirm cross-dock evidence produces validation/scope language rather than a standard-support claim.

## Corrected installer R1

If the initial v0.8.5 installer stopped at the Ruff F401 validation gate, the corrected installer recognizes the exact failed state only when the repository remains on `feature/configuration-intelligence-v0.8.5` at the verified v0.8.4 base commit. It backs up the dirty state under the versioned installer folder, resets that known failed attempt, reapplies the corrected package, and reruns the complete validation. Unrelated dirty repository states are still refused.
