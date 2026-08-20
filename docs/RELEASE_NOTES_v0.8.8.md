# v0.8.8 Release Notes

## Case-insensitive usernames

- Username capitalization is preserved exactly as created after surrounding whitespace is removed.
- Authentication accepts upper-, lower-, or mixed-case variants of the same username.
- Username duplicate detection is now case-insensitive.
- Passwords remain case-sensitive.
- Existing user records are backfilled with a unique normalized username key.
- Migration stops safely if the database already contains usernames that collide when case is ignored.

## Preserved baseline

All v0.8.7 user role editing, Active/Inactive lifecycle, password reset, ownership reassignment, session revocation, evidence privacy, speech preferences, configuration intelligence, reporting, and AI-text behavior remain unchanged.
