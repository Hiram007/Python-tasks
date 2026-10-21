"""SQLAlchemy data model for the Employee of the Month process."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.roles import parse_roles
from app.timeutil import month_label, utcnow


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Status vocabularies
# --------------------------------------------------------------------------

CYCLE_OPEN = "OPEN"
CYCLE_REVIEW = "REVIEW"
CYCLE_SHORTLISTED = "SHORTLISTED"
CYCLE_VOTING = "VOTING"
CYCLE_TIE_PENDING = "TIE_PENDING"
CYCLE_COMPLETED = "COMPLETED"

CYCLE_STATUS_LABELS = {
    CYCLE_OPEN: "Nominations open",
    CYCLE_REVIEW: "Panel review",
    CYCLE_SHORTLISTED: "Shortlisted",
    CYCLE_VOTING: "Final voting",
    CYCLE_TIE_PENDING: "Tie – resolution required",
    CYCLE_COMPLETED: "Completed",
}

NOM_SUBMITTED = "SUBMITTED"
NOM_UNDER_REVIEW = "UNDER_REVIEW"
NOM_APPROVED = "APPROVED"
NOM_REJECTED = "REJECTED"

NOM_STATUS_LABELS = {
    NOM_SUBMITTED: "Submitted",
    NOM_UNDER_REVIEW: "Under review",
    NOM_APPROVED: "Approved",
    NOM_REJECTED: "Rejected",
}

DECISION_APPROVE = "APPROVE"
DECISION_REJECT = "REJECT"

PANEL_INITIAL = "INITIAL"
PANEL_FINAL = "FINAL"

PANEL_TYPE_LABELS = {PANEL_INITIAL: "Initial Review Panel", PANEL_FINAL: "Final Voting Panel"}

ROUND_OPEN = "OPEN"
ROUND_CLOSED = "CLOSED"

WINNER_DECLARED = "DECLARED"
WINNER_TIE_PENDING = "TIE_PENDING_RESOLUTION"
WINNER_RESOLVED = "RESOLVED"

WINNER_STATUS_LABELS = {
    WINNER_DECLARED: "Winner declared",
    WINNER_TIE_PENDING: "Tie – resolution required",
    WINNER_RESOLVED: "Tie resolved",
}

NOTIFY_SENT = "SENT"
NOTIFY_FAILED = "FAILED"
NOTIFY_UNSENT = "UNSENT"

NOTIFY_STATUS_LABELS = {
    NOTIFY_SENT: "Sent",
    NOTIFY_FAILED: "Failed",
    NOTIFY_UNSENT: "Not sent",
}

LEVEL_EXECUTIVE = "Executive Manager"
LEVEL_MANAGER = "Manager"
LEVEL_SPECIALIST = "Specialist"
LEVEL_OFFICER = "Officer"
LEVEL_GENERAL = "General"

MANAGEMENT_LEVELS = [LEVEL_EXECUTIVE, LEVEL_MANAGER, LEVEL_SPECIALIST, LEVEL_OFFICER, LEVEL_GENERAL]


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    department: Mapped[str] = mapped_column(String(80), nullable=False, default="Unassigned")
    job_title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    management_level: Mapped[str] = mapped_column(String(40), nullable=False, default=LEVEL_GENERAL)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    panel_member: Mapped["PanelMember | None"] = relationship(back_populates="employee", uselist=False)
    user: Mapped["User | None"] = relationship(back_populates="employee", uselist=False)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def initials(self) -> str:
        return (self.first_name[:1] + self.last_name[:1]).upper()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Employee {self.employee_number} {self.full_name}>"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[str] = mapped_column(String(160), nullable=False, default="EMPLOYEE")
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    employee: Mapped["Employee | None"] = relationship(back_populates="user")

    @property
    def role_list(self) -> list[str]:
        return parse_roles(self.roles)

    def has_role(self, *roles: str) -> bool:
        owned = set(self.role_list)
        return bool(owned.intersection(roles))


class PanelMember(Base, TimestampMixin):
    """A member of the single master Recognition Panel."""

    __tablename__ = "panel_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False)
    management_level: Mapped[str] = mapped_column(String(40), nullable=False, default=LEVEL_MANAGER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deactivated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="panel_member")

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() if parts else "?"


# --------------------------------------------------------------------------
# Recognition cycle and panel assignments
# --------------------------------------------------------------------------


class RecognitionCycle(Base, TimestampMixin):
    __tablename__ = "recognition_cycles"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_cycle_year_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_key: Mapped[str] = mapped_column(String(7), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=CYCLE_OPEN)

    nomination_opens_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    nomination_closes_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    threshold_nominations: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    required_initial_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    approval_min_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    panels_assigned_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    panel_signature: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shortlist_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    voting_opened_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    winner_declared_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    nominations: Mapped[list["Nomination"]] = relationship(back_populates="cycle")
    assignments: Mapped[list["PanelAssignment"]] = relationship(
        back_populates="cycle", cascade="all, delete-orphan"
    )

    @property
    def label(self) -> str:
        return month_label(self.year, self.month)

    @property
    def status_label(self) -> str:
        return CYCLE_STATUS_LABELS.get(self.status, self.status)

    @property
    def panels_locked(self) -> bool:
        return self.panels_assigned_at is not None


class PanelAssignment(Base, TimestampMixin):
    __tablename__ = "panel_assignments"
    __table_args__ = (
        UniqueConstraint("cycle_id", "panel_type", "panel_member_id", name="uq_assignment_unique_member"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("recognition_cycles.id"), nullable=False, index=True)
    panel_type: Mapped[str] = mapped_column(String(16), nullable=False)
    panel_member_id: Mapped[int] = mapped_column(ForeignKey("panel_members.id"), nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    cycle: Mapped["RecognitionCycle"] = relationship(back_populates="assignments")
    member: Mapped["PanelMember"] = relationship()

    @property
    def panel_label(self) -> str:
        return PANEL_TYPE_LABELS.get(self.panel_type, self.panel_type)


# --------------------------------------------------------------------------
# Nominations, reviews, shortlisting, voting
# --------------------------------------------------------------------------


class Nomination(Base, TimestampMixin):
    __tablename__ = "nominations"
    __table_args__ = (
        UniqueConstraint("cycle_id", "nominator_id", "nominee_id", name="uq_nomination_pair_per_cycle"),
        Index("ix_nomination_cycle_status", "cycle_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("recognition_cycles.id"), nullable=False)
    nominee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    nominator_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    department: Mapped[str] = mapped_column(String(80), nullable=False)
    achievement_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    achievement_description: Mapped[str] = mapped_column(Text, nullable=False)
    motivation: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=NOM_SUBMITTED)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    cycle: Mapped["RecognitionCycle"] = relationship(back_populates="nominations")
    nominee: Mapped["Employee"] = relationship(foreign_keys=[nominee_id])
    nominator: Mapped["Employee"] = relationship(foreign_keys=[nominator_id])
    reviews: Mapped[list["PanelReview"]] = relationship(
        back_populates="nomination", cascade="all, delete-orphan"
    )

    @property
    def status_label(self) -> str:
        return NOM_STATUS_LABELS.get(self.status, self.status)

    @property
    def review_count(self) -> int:
        return len(self.reviews)

    @property
    def approve_count(self) -> int:
        return sum(1 for r in self.reviews if r.decision == DECISION_APPROVE)

    @property
    def reject_count(self) -> int:
        return sum(1 for r in self.reviews if r.decision == DECISION_REJECT)

    def is_decided(self) -> bool:
        return self.status in (NOM_APPROVED, NOM_REJECTED)


class PanelReview(Base, TimestampMixin):
    __tablename__ = "panel_reviews"
    __table_args__ = (
        UniqueConstraint("nomination_id", "reviewer_id", name="uq_review_once_per_reviewer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nomination_id: Mapped[int] = mapped_column(ForeignKey("nominations.id"), nullable=False, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("recognition_cycles.id"), nullable=False, index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("panel_members.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(12), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    nomination: Mapped["Nomination"] = relationship(back_populates="reviews")
    reviewer: Mapped["PanelMember"] = relationship()

    @property
    def decision_label(self) -> str:
        return "Approve" if self.decision == DECISION_APPROVE else "Reject"


class ShortlistEntry(Base, TimestampMixin):
    __tablename__ = "shortlist_entries"
    __table_args__ = (UniqueConstraint("cycle_id", "nomination_id", name="uq_shortlist_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("recognition_cycles.id"), nullable=False, index=True)
    nomination_id: Mapped[int] = mapped_column(ForeignKey("nominations.id"), nullable=False)
    final_vote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    nomination: Mapped["Nomination"] = relationship()


class VotingRound(Base, TimestampMixin):
    __tablename__ = "voting_rounds"
    __table_args__ = (UniqueConstraint("cycle_id", name="uq_one_round_per_cycle"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("recognition_cycles.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ROUND_OPEN)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    total_votes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    cycle: Mapped["RecognitionCycle"] = relationship()
    ballot: Mapped["FinalBallot | None"] = relationship(back_populates="round", uselist=False)


class FinalBallot(Base, TimestampMixin):
    """The ballot for a voting round: the approved, shortlisted candidates."""

    __tablename__ = "final_ballots"
    __table_args__ = (UniqueConstraint("voting_round_id", name="uq_ballot_per_round"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    voting_round_id: Mapped[int] = mapped_column(ForeignKey("voting_rounds.id"), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    round: Mapped["VotingRound"] = relationship(back_populates="ballot")
    candidates: Mapped[list["FinalBallotCandidate"]] = relationship(
        back_populates="ballot", cascade="all, delete-orphan"
    )


class FinalBallotCandidate(Base, TimestampMixin):
    __tablename__ = "final_ballot_candidates"
    __table_args__ = (UniqueConstraint("ballot_id", "nomination_id", name="uq_candidate_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ballot_id: Mapped[int] = mapped_column(ForeignKey("final_ballots.id"), nullable=False, index=True)
    nomination_id: Mapped[int] = mapped_column(ForeignKey("nominations.id"), nullable=False)

    ballot: Mapped["FinalBallot"] = relationship(back_populates="candidates")
    nomination: Mapped["Nomination"] = relationship()


class FinalVote(Base, TimestampMixin):
    __tablename__ = "final_votes"
    __table_args__ = (
        UniqueConstraint("voting_round_id", "voter_id", name="uq_one_vote_per_voter_per_round"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    voting_round_id: Mapped[int] = mapped_column(ForeignKey("voting_rounds.id"), nullable=False, index=True)
    ballot_id: Mapped[int] = mapped_column(ForeignKey("final_ballots.id"), nullable=False)
    voter_id: Mapped[int] = mapped_column(ForeignKey("panel_members.id"), nullable=False)
    nomination_id: Mapped[int] = mapped_column(ForeignKey("nominations.id"), nullable=False)
    cast_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    voter: Mapped["PanelMember"] = relationship()
    nomination: Mapped["Nomination"] = relationship()


class WinnerRecord(Base, TimestampMixin):
    __tablename__ = "winner_records"
    __table_args__ = (UniqueConstraint("cycle_id", name="uq_winner_per_cycle"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("recognition_cycles.id"), nullable=False)
    voting_round_id: Mapped[int] = mapped_column(ForeignKey("voting_rounds.id"), nullable=False)
    winner_nomination_id: Mapped[int | None] = mapped_column(ForeignKey("nominations.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(28), nullable=False, default=WINNER_DECLARED)
    winning_votes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_tie: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tie_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_identity: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    declared_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    cycle: Mapped["RecognitionCycle"] = relationship()
    winner_nomination: Mapped["Nomination | None"] = relationship()
    resolved_by: Mapped["User | None"] = relationship()

    @property
    def status_label(self) -> str:
        return WINNER_STATUS_LABELS.get(self.status, self.status)


# --------------------------------------------------------------------------
# Notifications, audit, settings
# --------------------------------------------------------------------------


class NotificationLog(Base, TimestampMixin):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("recognition_cycles.id"), nullable=True)
    template_key: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False, default="INFORMATIONAL")
    recipient_email: Mapped[str] = mapped_column(String(180), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=NOTIFY_UNSENT)
    transport: Mapped[str] = mapped_column(String(24), nullable=False, default="outbox")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    related_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_attempt_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def status_label(self) -> str:
        return NOTIFY_STATUS_LABELS.get(self.status, self.status)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(160), nullable=False, default="system")
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


ALL_MODELS = [
    Employee,
    User,
    PanelMember,
    RecognitionCycle,
    PanelAssignment,
    Nomination,
    PanelReview,
    ShortlistEntry,
    VotingRound,
    FinalBallot,
    FinalBallotCandidate,
    FinalVote,
    WinnerRecord,
    NotificationLog,
    AuditEvent,
    SystemSetting,
]
