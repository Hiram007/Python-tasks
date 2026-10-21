"""Domain errors.

Services raise these; the HTTP layer turns them into user-facing messages
(validation banners, 403 pages, blocked-workflow alerts) so business rules are
enforced on the server rather than by hiding buttons.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for business-rule failures."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(DomainError):
    """Input failed validation."""


class PermissionDenied(DomainError):
    """The actor is not allowed to perform this action."""


class ConflictError(DomainError):
    """The action would create a duplicate or otherwise conflict."""


class WorkflowError(DomainError):
    """A workflow precondition is not met (shortlisting, voting, winner)."""


class AssignmentError(WorkflowError):
    """Panel assignment rules cannot be satisfied."""
