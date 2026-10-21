"""Roles and the authorisation matrix.

Role membership is stored per user as a comma-separated list, so one person can
hold several roles (a panel member is routinely both an initial reviewer in one
month and a final voter in the next).

Authorisation is enforced on the server: route dependencies check roles, and the
workflow services additionally check record-level assignments (a reviewer may
only review nominations assigned to them, a voter only their own ballot).
"""

from __future__ import annotations

SYSTEM_ADMIN = "SYSTEM_ADMIN"
HR_ADMIN = "HR_ADMIN"
EMPLOYEE = "EMPLOYEE"
INITIAL_PANEL = "INITIAL_PANEL"
FINAL_PANEL = "FINAL_PANEL"
MANAGEMENT = "MANAGEMENT"

ROLE_LABELS = {
    SYSTEM_ADMIN: "System Administrator",
    HR_ADMIN: "HR / Recognition Administrator",
    EMPLOYEE: "Employee / Nominator",
    INITIAL_PANEL: "Initial Review Panel Member",
    FINAL_PANEL: "Final Voting Panel Member",
    MANAGEMENT: "Read-only Management",
}

ROLE_ORDER = [SYSTEM_ADMIN, HR_ADMIN, EMPLOYEE, INITIAL_PANEL, FINAL_PANEL, MANAGEMENT]

# Convenience groupings used by route dependencies.
PANEL_ROLES = {INITIAL_PANEL, FINAL_PANEL}
ADMIN_ROLES = {SYSTEM_ADMIN}
HR_ROLES = {SYSTEM_ADMIN, HR_ADMIN}
STAFF_ROLES = {SYSTEM_ADMIN, HR_ADMIN, MANAGEMENT}
CONFIDENTIAL_ROLES = {SYSTEM_ADMIN, HR_ADMIN}
ALL_ROLES = set(ROLE_LABELS)


def parse_roles(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def normalise_roles(values) -> str:
    """Store a stable, deduplicated, canonical-order role list."""
    chosen = {str(v).strip().upper() for v in values if str(v).strip()}
    unknown = chosen - ALL_ROLES
    if unknown:
        raise ValueError(f"Unknown role(s): {', '.join(sorted(unknown))}")
    return ",".join(role for role in ROLE_ORDER if role in chosen)


def role_labels(raw: str | None) -> list[str]:
    return [ROLE_LABELS.get(role, role) for role in parse_roles(raw)]
