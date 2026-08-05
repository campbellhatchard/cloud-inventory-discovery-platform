# Case-Insensitive Username Authentication — v0.8.8

## Purpose

Permit usernames to contain and retain upper- and lowercase letters while allowing authentication with any capitalization that represents the same username.

## Controlled behavior

1. The username displayed in Administration, audit-linked user payloads, and account menus preserves the capitalization entered when the account was created.
2. Authentication compares a normalized username key produced by trimming surrounding whitespace and applying Unicode case folding.
3. Password comparison remains fully case-sensitive and continues to use Argon2id verification.
4. New-user duplicate checks use the normalized username key. `Campbell`, `campbell`, and `CAMPBELL` therefore identify the same account namespace and cannot be created as separate users.
5. Leading and trailing username whitespace is not stored and is ignored during login. Internal whitespace and punctuation remain part of the username.
6. Existing users receive a normalized username key through migration without changing the stored/displayed username.
7. The migration checks for existing case-insensitive collisions before changing the schema. If a collision exists, deployment stops and identifies the conflicting user IDs rather than selecting an account arbitrarily.
8. User roles, Active/Inactive state, password reset, forced password change, lockout, sessions, memberships, ownership, and audit attribution remain unchanged.

## Data model

`users.username` remains the preserved display/login name. `users.username_key` is a required unique indexed normalized value used only for lookup and uniqueness enforcement.

## Acceptance criteria

- A user created as `MiXeD.User_88` is displayed as `MiXeD.User_88`.
- The same account can authenticate as `mixed.user_88`, `MIXED.USER_88`, or any other case variation.
- Creating another user whose username differs only by capitalization returns a conflict.
- Surrounding spaces are trimmed during creation and ignored during authentication.
- Changing the case of any password character causes password verification to fail.
- Existing v0.8.7 usernames are backfilled without display changes.
