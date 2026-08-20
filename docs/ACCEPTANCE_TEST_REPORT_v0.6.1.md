# Acceptance Test Report - v0.6.1

## Scope

Section Photo Upload interim hotfix based on the deployed v0.6.0 staging commit `9fa87d0ae43bd56934d09fd40bd3a829c6697d22`.

## Acceptance coverage

The release adds regression coverage verifying that:

- every normal section has a direct section-photo upload action;
- PHOTO discovery prompts route to the direct section-photo workflow;
- the upload form accepts images and multiple selection;
- uploads are explicitly associated with the current section;
- default placement is INLINE and classification is CONFIDENTIAL;
- offline uploads reuse the existing evidence queue;
- a JPEG uploaded directly to an operational section is returned as PHOTO evidence and remains linked to the correct section;
- Quick Entry remains present and its existing contract is preserved.

The deployment installer also runs the repository's complete staging validation before commit or push. A failed validation stops the installer before GitHub mutation.

## Packaging validation

- `node --check app/static/app.js`: passed
- `python -m compileall -q app`: passed
- `pytest -q`: **46 passed**
- Ruff is not installed in the packaging container; the Windows deployment installer runs the project's complete `Deploy.ps1 -Action Validate` gate before commit/push.
