# User Administration, Evidence Privacy & Speech Preferences — v0.8.6

## Objective

v0.8.6 builds on the locked v0.8.5 Configuration Intelligence baseline and makes three controlled changes: stronger administrator user lifecycle actions, complete retirement of AI photograph interpretation, and device-local text-to-speech preferences.

## User administration

The application minimum password length is 10 characters. Existing complexity rules remain: at least three of lowercase, uppercase, numeric, and symbol characters.

New users may be created without entering a password in the browser. The web service obtains the temporary password from the secret `DEFAULT_USER_TEMP_PASSWORD`; the staging/production value is supplied only through the deployment environment. The secret is not stored in source code, generated client bundles, logs, or API responses. New users are forced to change the temporary password at first login.

Administrators may reset another active user's password. Reset uses the configured temporary password, revokes all active sessions, clears login lockout state, and sets `force_password_change=true`. Administrators change their own password through the normal Change Password workflow rather than resetting themselves.

Administrators may delete a user through a controlled soft deletion. The User row is retained for historical attribution, while active sessions, roles, prospect memberships, report memberships, and engagement memberships are removed and the account status becomes `DELETED`. A user cannot delete their own administrator account. A user who owns reports or engagements cannot be deleted until an active Owner or Administrator is selected as replacement. Ownership is reassigned and the replacement receives Owner-level prospect membership where required. Section assignments are reassigned when a replacement exists or cleared otherwise.

## Photograph AI retirement

Photographs remain first-class human evidence. Upload, native camera capture, captions, placement, move/delete controls, secure storage, image derivatives, and DOCX/PDF publication continue unchanged.

v0.8.6 removes all active AI interpretation of photographs:

- no photo-analysis API endpoint;
- no `PHOTO_ANALYSIS` worker lane or AI purpose;
- no `PHOTO_CONTEXT_REVISION` request purpose;
- no image/base64 payloads in AI service code;
- no photo-analysis UI, comparison UI, or acceptance workflow;
- no active `EvidenceAiObservation` model/table.

The migration blocks unfinished legacy photo-AI jobs, supersedes unapproved photo-AI suggestions, fails corresponding generic queued jobs, and drops the cached `evidence_ai_observations` table. Previously approved historical narrative remains part of immutable/version history but is not treated as a current photograph-analysis facility.

Human-entered photograph captions remain written evidence and are not themselves AI visual interpretation.

## Speech preferences

Text-to-speech continues to use the browser Web Speech API. The default is **System / Browser Default**, implemented by leaving `SpeechSynthesisUtterance.voice` unset so voice choice remains with the operating system/browser implementation.

Users may open Speech settings and select any voice exposed by `speechSynthesis.getVoices()`. The UI also supports Slow (0.85), Normal (1.0), and Faster (1.15) speaking rates plus Test Voice. Voice URI and rate are stored only in browser local storage. An unavailable saved voice automatically falls back to System / Browser Default.

A web browser cannot reliably read a Windows-specific system default speech voice setting directly, so the UI does not promise an exact Windows Settings voice identity; it uses the platform/browser default unless the user makes an explicit selection.

## Acceptance requirements

1. A 9-character new password is rejected and a compliant 10-character password is accepted.
2. A user created without a browser-supplied password can authenticate with the configured temporary password and is blocked from prospect content until changing it.
3. Admin reset revokes existing sessions and restores the configured temporary password with forced change.
4. User deletion preserves the User record but prevents login and removes active access relationships.
5. Owned reports/engagements require and receive a valid replacement owner with prospect access.
6. Photograph upload/publication remains functional while the legacy photo-analysis route is unavailable.
7. AI request schemas reject `PHOTO_CONTEXT_REVISION`; active worker/service code contains no photo AI lane or image payload path.
8. Speech settings default to System / Browser Default and allow device-exposed voice/rate selection with local persistence.
