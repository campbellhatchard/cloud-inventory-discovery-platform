# Deployment Package Validation — v0.8.7

- Source version identity: 0.8.7
- Locked baseline: v0.8.6 commit `4aaa7369de80e69e9f297c1dbc9be1705eacbfe6`
- Baseline migration: `k61h4c0f8d21`
- Release migration: `l72i5d1g9e32`
- Full regression: 105 passed
- JavaScript syntax: passed
- Python compilation: passed
- Fresh migration: passed
- v0.8.6 upgrade migration: passed
- OpenAPI: passed; role/status endpoints present; user DELETE route absent
- No new environment variables required
- Source archive excludes local databases, `.env`, caches, runtime outputs, and installer artifacts
- Windows Ruff/mypy/deployment validation remains mandatory before Git commit/push
## Corrected R1 package

The corrected R1 package removes the single Ruff F401 unused import identified by the first Windows validation attempt. The recovery-aware installer is pinned to the unchanged v0.8.6 baseline SHA, preserves the failed working tree before any reset, refuses unknown dirty states, and reruns full Windows validation before commit/push.

