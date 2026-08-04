# Release Notes — v0.8.6

## User Administration, Evidence Privacy & Speech Preferences

v0.8.6 builds on v0.8.5 Configuration Intelligence.

### User administration

- Added administrator password reset for other active users.
- Reset revokes all target sessions, clears lockout state, assigns the configured temporary password, and forces password change at next login.
- New users use the configured temporary password when no custom password is supplied.
- Reduced password minimum length to 10 while retaining complexity controls.
- Added controlled user deletion with historical User-row preservation, access/session revocation, self-delete protection, ownership reassignment, and replacement prospect membership.
- Added web-service secret `DEFAULT_USER_TEMP_PASSWORD`; the value is deployment-managed and is not stored in the repository.

### Evidence privacy

- Removed independent AI photograph analysis.
- Removed photo-to-Current-Operations AI comparison and revision.
- Removed `PHOTO_ANALYSIS` worker processing and image payload handling.
- Photographs remain available for human review, captions, section placement, and report publication.
- Migration retires pending legacy photo AI activity and removes the cached photo-observation table.

### Speech

- Added Speech settings from the account menu.
- Default voice is System / Browser Default.
- Users can select voices exposed by the current device/browser.
- Added Slow, Normal, and Faster speaking rates plus Test Voice.
- Preferences are device/browser-local and fall back safely when a saved voice disappears.

### Environment impact

Web service requires a new secret:

`DEFAULT_USER_TEMP_PASSWORD` with the approved temporary-password value

The worker does not require this secret.
