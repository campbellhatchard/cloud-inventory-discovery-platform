# User Lifecycle & Role Administration — v0.8.7

## Objective
Replace user deletion with reversible Active/Inactive lifecycle control and add administrator-managed global roles.

## Lifecycle
- ACTIVE users may authenticate and appear in collaboration assignment selectors.
- INACTIVE users cannot authenticate and are excluded from collaboration assignment selectors.
- Administrators can still see both ACTIVE and INACTIVE users.
- Deactivation revokes sessions immediately but preserves roles, memberships, audit attribution, authored content, and historical references.
- Reactivation restores authentication eligibility without recreating the user.
- A user cannot deactivate their own account, and the last active Administrator cannot be deactivated.
- If an account owns reports or engagements, an active Owner/Administrator replacement is required before deactivation.

## Role administration
Administrators can assign any combination of CONTRIBUTOR, REVIEWER, OWNER, and ADMIN, with at least one role required. The last active Administrator cannot lose ADMIN. OWNER cannot be removed while the account still owns reports or engagements.

## Legacy conversion
The v0.8.7 migration converts v0.8.6 `DELETED` user rows to `INACTIVE`. Any roles/memberships already removed by a prior v0.8.6 delete cannot be reconstructed automatically; an Administrator can reassign roles before activation.
