"""Role hierarchy and authorization helpers.

Roles are ordered, not a flat set of independent capabilities. An admin can do
anything an auditor can, and so on down. Encoding that as a rank comparison
means an endpoint declares the *minimum* role it needs and never has to be
updated when a new role is inserted into the middle of the hierarchy.
"""

from __future__ import annotations

from fai.db.models.enums import UserRole

# Higher rank means more privilege. The gaps leave room to insert a role
# without renumbering the others.
ROLE_RANK: dict[UserRole, int] = {
    UserRole.VIEWER: 10,
    UserRole.REVIEWER: 20,
    UserRole.AUDITOR: 30,
    UserRole.ADMIN: 40,
}


def rank(role: UserRole | str) -> int:
    """Return the privilege rank of a role.

    An unrecognised role ranks below every real one. A corrupted or
    forward-dated role value must fail closed, never open.
    """
    try:
        return ROLE_RANK[UserRole(role)]
    except (KeyError, ValueError):
        return -1


def has_at_least(actual: UserRole | str, required: UserRole) -> bool:
    """True when ``actual`` is at least as privileged as ``required``."""
    return rank(actual) >= rank(required)


# Capability names used by endpoints, mapped to the minimum role that holds
# them. Keeping these here rather than inline at each route means the whole
# authorization surface can be read in one place, and audited in one place.
CAPABILITY_MINIMUM: dict[str, UserRole] = {
    # Read-only access to statements, flags, search, and reports.
    "data:read": UserRole.VIEWER,
    # Acknowledge, dismiss, or comment on a finding.
    "flags:triage": UserRole.REVIEWER,
    # Upload documents and run analysis.
    "documents:write": UserRole.AUDITOR,
    "analysis:run": UserRole.AUDITOR,
    "reports:generate": UserRole.AUDITOR,
    # Manage the organization, its members, and their roles.
    "org:manage": UserRole.ADMIN,
    "users:manage": UserRole.ADMIN,
}


def can(role: UserRole | str, capability: str) -> bool:
    """True when a role holds a named capability."""
    required = CAPABILITY_MINIMUM.get(capability)
    if required is None:
        # An unknown capability is a programming error, and the safe reading of
        # one is denial.
        return False
    return has_at_least(role, required)
