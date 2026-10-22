"""Acceptance tests for the recognition workflow.

Every scenario runs against an isolated, freshly created database and drives the
real service layer (the same code the web routes call). Nothing is simulated:
if a rule is broken, the scenario fails and says why.

`pytest` runs the same scenarios through `tests/test_acceptance.py`, so the
screen and CI cannot drift apart.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import build_engine
from app.errors import ConflictError, PermissionDenied, WorkflowError
from app.models import (
    DECISION_APPROVE,
    DECISION_REJECT,
    NOTIFY_SENT,
    Nomination,
    NotificationLog,
    PanelMember,
    PanelReview,
    RecognitionCycle,
    ShortlistEntry,
    SystemSetting,
    User,
    VotingRound,
    WinnerRecord,
)
from app.roles import HR_ROLES, SYSTEM_ADMIN
from app.security import create_session_token, require_roles
from app.seed import seed_people
from app.services import (
    cycles,
    panels,
    reviews,
    settings_service,
    shortlisting,
    voting,
    winners,
)
from app.services import nominations as nomination_service
from app.timeutil import utcnow

log = logging.getLogger(__name__)

LAST_RUN_KEY = "last_acceptance_run"

NOM_PAIRS = [
    (1010, 1014),
    (1011, 1015),
    (1012, 1016),
    (1013, 1017),
    (1014, 1018),
    (1015, 1019),
    (1016, 1020),
]


@dataclass
class ScenarioResult:
    id: int
    name: str
    expected: str
    actual: str
    passed: bool
    detail: str = ""


@dataclass
class Fixture:
    """Deterministic test context built from the seeded directory."""

    db: Session
    cycle: RecognitionCycle
    notes: list[str] = field(default_factory=list)

    def employee(self, number: int):
        from app.models import Employee

        return self.db.scalar(select(Employee).where(Employee.employee_number == f"CAS-{number}"))

    def initial_reviewers(self) -> list[PanelMember]:
        return panels.members_for(self.db, self.cycle, "INITIAL")

    def final_voters(self) -> list[PanelMember]:
        return panels.members_for(self.db, self.cycle, "FINAL")

    def nominate(self, index: int) -> Nomination:
        nominator_no, nominee_no = NOM_PAIRS[index]
        nominator = self.employee(nominator_no)
        nominee = self.employee(nominee_no)
        return nomination_service.submit_nomination(
            self.db,
            actor=None,
            cycle=self.cycle,
            nominee=nominee,
            nominator=nominator,
            department=nominee.department,
            achievement_date=dt.date.today() - dt.timedelta(days=5),
            achievement_description=(
                f"Delivered a measurable improvement in {nominee.department} during the recognition "
                f"month (scenario nomination {index + 1})."
            ),
            motivation=(
                "This colleague consistently goes beyond the brief, supports the team and demonstrates "
                "the values we want to recognise."
            ),
        )

    def review(self, nomination: Nomination, reviewer: PanelMember, decision: str):
        return reviews.submit_review(
            self.db,
            nomination=nomination,
            reviewer=reviewer,
            decision=decision,
            comments="Scenario evidence reviewed.",
            actor=None,
        )

    def complete(self, nomination: Nomination, decisions: list[str] | None = None):
        decisions = decisions or [DECISION_APPROVE] * self.cycle.required_initial_reviews
        for reviewer, decision in zip(self.initial_reviewers(), decisions):
            self.review(nomination, reviewer, decision)
        return nomination


def _session() -> tuple[Session, "object"]:
    engine = build_engine("sqlite://")
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    settings_service.seed_defaults(db)
    seed_people(db)
    db.commit()
    return db, engine


def _fixture(month_offset: int = 0) -> Fixture:
    db, _engine = _session()
    today = dt.date.today()
    month = today.month + month_offset
    year = today.year
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    cycle = cycles.get_or_create_cycle(db, year, month)
    panels.assign_panels(db, cycle, None)
    db.commit()
    return Fixture(db=db, cycle=cycle)


def _votes_for(fixture: Fixture, round_, nomination_ids: list[int]):
    """Cast one vote per final voter, cycling through the given candidate ids."""
    cast = []
    for index, voter in enumerate(fixture.final_voters()):
        target = nomination_ids[index % len(nomination_ids)]
        cast.append(
            voting.cast_vote(
                fixture.db, cycle=fixture.cycle, voter=voter, nomination_id=target, actor=None
            )
        )
    return cast


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------


def s01_six_nominations(db, fx: Fixture):
    for index in range(6):
        fx.complete(fx.nominate(index))
    state = shortlisting.eligibility(db, fx.cycle)
    blocked = False
    try:
        shortlisting.run_shortlist(db, fx.cycle, actor=None)
    except WorkflowError:
        blocked = True
    rounds = db.scalars(select(VotingRound).where(VotingRound.cycle_id == fx.cycle.id)).all()
    entries = db.scalars(select(ShortlistEntry).where(ShortlistEntry.cycle_id == fx.cycle.id)).all()
    expected = "Shortlisting refused and no voting round opened with only 6 nominations"
    actual = (
        f"can_shortlist={state['can_shortlist']}, run refused={blocked}, "
        f"voting rounds={len(rounds)}, shortlist entries={len(entries)}"
    )
    return expected, actual, (not state["can_shortlist"]) and blocked and not rounds and not entries


def s02_one_outstanding_review(db, fx: Fixture):
    nominations = []
    for index in range(7):
        nomination = fx.nominate(index)
        if index < 6:
            fx.complete(nomination)
        else:
            for reviewer in fx.initial_reviewers()[:3]:
                fx.review(nomination, reviewer, DECISION_APPROVE)
        nominations.append(nomination)
    state = shortlisting.eligibility(db, fx.cycle)
    expected = "Shortlisting refused while one nomination still has an outstanding review"
    actual = (
        f"nominations={state['nomination_count']}, threshold_met={state['threshold_met']}, "
        f"reviews_complete={state['reviews_complete']}, can_shortlist={state['can_shortlist']}"
    )
    return (
        expected,
        actual,
        state["nomination_count"] == 7
        and state["threshold_met"]
        and not state["reviews_complete"]
        and not state["can_shortlist"],
    )


def s03_all_rejected(db, fx: Fixture):
    for index in range(7):
        fx.complete(fx.nominate(index), [DECISION_REJECT] * 4)
    state = shortlisting.eligibility(db, fx.cycle)
    result = shortlisting.run_shortlist(db, fx.cycle, actor=None)
    rounds = db.scalars(select(VotingRound).where(VotingRound.cycle_id == fx.cycle.id)).all()
    entries = db.scalars(select(ShortlistEntry).where(ShortlistEntry.cycle_id == fx.cycle.id)).all()
    alerts = db.scalars(
        select(NotificationLog).where(NotificationLog.template_key == "workflow_error")
    ).all()
    expected = "No shortlist and no final voting when zero nominations are approved; admin notified"
    actual = (
        f"approved={state['approved_count']}, opened_voting={result['opened_voting']}, "
        f"voting rounds={len(rounds)}, shortlist entries={len(entries)}, admin alerts={len(alerts)}"
    )
    return (
        expected,
        actual,
        state["approved_count"] == 0
        and result["opened_voting"] is False
        and not rounds
        and not entries
        and len(alerts) >= 1,
    )


def s04_only_approved_shortlisted(db, fx: Fixture):
    approved = []
    for index in range(7):
        nomination = fx.nominate(index)
        if index < 2:
            fx.complete(nomination, [DECISION_APPROVE] * 4)
            approved.append(nomination)
        else:
            fx.complete(nomination, [DECISION_REJECT] * 4)
    result = shortlisting.run_shortlist(db, fx.cycle, actor=None)
    entries = db.scalars(select(ShortlistEntry).where(ShortlistEntry.cycle_id == fx.cycle.id)).all()
    round_ = voting.current_round(db, fx.cycle)
    candidates = voting.ballot_candidates(db, round_) if round_ else []
    expected = "Only the 2 approved nominations are shortlisted and appear on the ballot"
    actual = (
        f"shortlist entries={len(entries)}, opened_voting={result['opened_voting']}, "
        f"ballot candidates={len(candidates)}"
    )
    return (
        expected,
        actual,
        len(entries) == 2
        and result["opened_voting"] is True
        and len(candidates) == 2
        and {c.nomination_id for c in candidates} == {n.id for n in approved},
    )


def s05_four_unique_reviewers(db, fx: Fixture):
    nomination = fx.nominate(0)
    reviewers = fx.initial_reviewers()
    for reviewer in reviewers:
        fx.review(nomination, reviewer, DECISION_APPROVE)
    duplicate_blocked = False
    try:
        fx.review(nomination, reviewers[0], DECISION_REJECT)
    except ConflictError:
        duplicate_blocked = True
    stored = db.scalars(select(PanelReview).where(PanelReview.nomination_id == nomination.id)).all()
    unique_reviewers = {r.reviewer_id for r in stored}
    expected = "Exactly four distinct reviewers, and a repeat review is refused"
    actual = (
        f"initial panel={len(reviewers)}, distinct reviewers={len(unique_reviewers)}, "
        f"stored reviews={len(stored)}, duplicate refused={duplicate_blocked}"
    )
    return expected, actual, len(reviewers) == 4 and len(unique_reviewers) == 4 and duplicate_blocked


def s06_panel_sizes(db, fx: Fixture):
    initial = fx.initial_reviewers()
    final = fx.final_voters()
    expected = "Initial Review Panel has 4 members and Final Voting Panel has 4 members"
    actual = f"initial={len(initial)}, final={len(final)}"
    return expected, actual, len(initial) == 4 and len(final) == 4


def s07_one_shared_member(db, fx: Fixture):
    initial = {m.id for m in fx.initial_reviewers()}
    final = {m.id for m in fx.final_voters()}
    shared = initial & final
    expected = "Exactly one member shared; seven unique members in total"
    actual = f"shared={len(shared)}, unique={len(initial | final)}"
    return expected, actual, len(shared) == 1 and len(initial | final) == 7


def s08_assignments_stable(db, fx: Fixture):
    before = sorted(
        (a.panel_type, a.panel_member_id) for a in panels.existing_assignments(db, fx.cycle)
    )
    signature = fx.cycle.panel_signature
    panels.assign_panels(db, fx.cycle, None)
    panels.send_review_requests(db, fx.cycle, actor=None)
    fx.complete(fx.nominate(0))
    fx.nominate(1)
    db.refresh(fx.cycle)
    after = sorted(
        (a.panel_type, a.panel_member_id) for a in panels.existing_assignments(db, fx.cycle)
    )
    expected = "Re-running assignment and adding nominations leaves the saved panels unchanged"
    actual = (
        f"assignments before={len(before)} after={len(after)}, unchanged={before == after}, "
        f"signature stable={signature == fx.cycle.panel_signature}"
    )
    return expected, actual, before == after and signature == fx.cycle.panel_signature


def s09_duplicates_do_not_inflate(db, fx: Fixture):
    for index in range(7):
        fx.complete(fx.nominate(index))
    shortlisting.run_shortlist(db, fx.cycle, actor=None)
    round_ = voting.current_round(db, fx.cycle)
    candidates = [c.nomination_id for c in voting.ballot_candidates(db, round_)]

    reviewer = fx.initial_reviewers()[0]
    review_duplicate_blocked = False
    try:
        fx.review(fx.cycle.nominations[0], reviewer, DECISION_REJECT)
    except ConflictError:
        review_duplicate_blocked = True

    voter = fx.final_voters()[0]
    voting.cast_vote(db, cycle=fx.cycle, voter=voter, nomination_id=candidates[0], actor=None)
    vote_duplicate_blocked = False
    try:
        voting.cast_vote(db, cycle=fx.cycle, voter=voter, nomination_id=candidates[1], actor=None)
    except ConflictError:
        vote_duplicate_blocked = True

    db.refresh(round_)
    expected = "A repeated review and a repeated vote are both refused without changing the totals"
    actual = (
        f"review duplicate refused={review_duplicate_blocked}, "
        f"vote duplicate refused={vote_duplicate_blocked}, votes recorded={round_.total_votes}"
    )
    return (
        expected,
        actual,
        review_duplicate_blocked and vote_duplicate_blocked and int(round_.total_votes) == 1,
    )


def s10_only_shortlisted_on_ballot(db, fx: Fixture):
    approved, rejected = None, None
    for index in range(7):
        nomination = fx.nominate(index)
        if index == 0:
            fx.complete(nomination, [DECISION_APPROVE] * 4)
            approved = nomination
        else:
            fx.complete(nomination, [DECISION_REJECT] * 4)
            rejected = nomination
    shortlisting.run_shortlist(db, fx.cycle, actor=None)
    round_ = voting.current_round(db, fx.cycle)
    voter = fx.final_voters()[0]
    refused = False
    try:
        voting.cast_vote(db, cycle=fx.cycle, voter=voter, nomination_id=rejected.id, actor=None)
    except Exception as exc:  # noqa: BLE001 - the point is that it is refused
        refused = isinstance(exc, (WorkflowError, ConflictError, PermissionDenied)) or exc.__class__.__name__ == "ValidationError"
    round_.total_votes = 0
    db.flush()
    allowed = voting.cast_vote(db, cycle=fx.cycle, voter=voter, nomination_id=approved.id, actor=None)
    expected = "A rejected nomination is refused on the ballot; a shortlisted one is accepted"
    actual = f"rejected refused={refused}, approved accepted={allowed is not None}"
    return expected, actual, refused and allowed is not None


def s11_four_votes_calculate_winner(db, fx: Fixture):
    approved = []
    for index in range(7):
        nomination = fx.nominate(index)
        if index < 3:
            fx.complete(nomination, [DECISION_APPROVE] * 4)
            approved.append(nomination)
        else:
            fx.complete(nomination, [DECISION_REJECT] * 4)
    shortlisting.run_shortlist(db, fx.cycle, actor=None)
    round_ = voting.current_round(db, fx.cycle)

    voters = fx.final_voters()
    targets = [approved[0].id, approved[0].id, approved[0].id, approved[1].id]
    for voter, target in zip(voters, targets):
        voting.cast_vote(db, cycle=fx.cycle, voter=voter, nomination_id=target, actor=None)

    db.refresh(round_)
    record = winners.get_winner(db, fx.cycle)
    expected = "Four valid votes declare a winner with the highest valid vote count"
    actual = (
        f"votes recorded={round_.total_votes}, round status={round_.status}, "
        f"winner={(record.winner_nomination.nominee.full_name if record and record.winner_nomination else None)}, "
        f"winning votes={record.winning_votes if record else None}"
    )
    return (
        expected,
        actual,
        int(round_.total_votes) == 4
        and record is not None
        and record.status == "DECLARED"
        and record.winner_nomination_id == approved[0].id
        and record.winning_votes == 3,
    )


def s12_tie_escalates(db, fx: Fixture):
    approved = []
    for index in range(7):
        nomination = fx.nominate(index)
        if index < 2:
            fx.complete(nomination, [DECISION_APPROVE] * 4)
            approved.append(nomination)
        else:
            fx.complete(nomination, [DECISION_REJECT] * 4)
    shortlisting.run_shortlist(db, fx.cycle, actor=None)
    _votes_for(fx, voting.current_round(db, fx.cycle), [approved[0].id, approved[1].id])

    record = winners.get_winner(db, fx.cycle)
    db.refresh(fx.cycle)
    # Snapshot the tie state now: resolve_tie mutates the same ORM row, so these
    # values must be read before resolution to assert what the tie produced.
    tie_status = record.status
    tie_winner_id = record.winner_nomination_id
    cycle_status_at_tie = fx.cycle.status
    tie_alerts = db.scalars(
        select(NotificationLog).where(NotificationLog.template_key == "tie_notification")
    ).all()
    winner_mail_before = db.scalars(
        select(NotificationLog).where(NotificationLog.template_key == "winner_announcement")
    ).all()

    admin = db.scalar(select(User).where(User.email == "hr@casidra.co.za"))
    resolved = winners.resolve_tie(
        db,
        cycle=fx.cycle,
        nomination_id=approved[1].id,
        reason="Panel chair reviewed the supporting evidence submitted with each nomination.",
        actor=admin,
    )
    winner_mail_after = db.scalars(
        select(NotificationLog).where(NotificationLog.template_key == "winner_announcement")
    ).all()
    expected = (
        "A tie escalates for resolution with no automatic winner, then resolves with a reason and "
        "identity, preserving the original votes"
    )
    actual = (
        f"status={tie_status}, cycle={cycle_status_at_tie}, tie alerts={len(tie_alerts)}, "
        f"winner emails before resolution={len(winner_mail_before)}, after={len(winner_mail_after)}, "
        f"resolved winner={resolved.winner_nomination.nominee.full_name}, "
        f"identity set={bool(resolved.resolution_identity)}, votes preserved="
        f"{len(voting.tally(db, voting.current_round(db, fx.cycle)))} candidate totals"
    )
    return (
        expected,
        actual,
        tie_status == "TIE_PENDING_RESOLUTION"
        and tie_winner_id is None
        and cycle_status_at_tie == "TIE_PENDING"
        and len(tie_alerts) >= 1
        and not winner_mail_before
        and len(winner_mail_after) >= 1
        and resolved.status == "RESOLVED"
        and bool(resolved.resolution_reason)
        and bool(resolved.resolution_identity)
        and resolved.resolved_at is not None,
    )


def s13_other_months_isolated(db, fx: Fixture):
    # A previous month with its own completed round must not influence this one.
    other = _fixture(month_offset=-1)
    previous = []
    for index in range(7):
        nomination = other.nominate(index)
        if index < 2:
            other.complete(nomination, [DECISION_APPROVE] * 4)
            previous.append(nomination)
        else:
            other.complete(nomination, [DECISION_REJECT] * 4)
    shortlisting.run_shortlist(other.db, other.cycle, actor=None)
    # A unanimous previous month, so it records a decisive winner rather than a tie:
    # the scenario is about month isolation, not tie handling (see scenario 12).
    _votes_for(other, voting.current_round(other.db, other.cycle), [previous[0].id])
    other_record = winners.get_winner(other.db, other.cycle)

    approved = []
    for index in range(7):
        nomination = fx.nominate(index)
        if index < 3:
            fx.complete(nomination, [DECISION_APPROVE] * 4)
            approved.append(nomination)
        else:
            fx.complete(nomination, [DECISION_REJECT] * 4)
    shortlisting.run_shortlist(db, fx.cycle, actor=None)
    _votes_for(fx, voting.current_round(db, fx.cycle), [approved[2].id] * 4)
    record = winners.get_winner(db, fx.cycle)

    expected = "Votes from another month cannot affect the current winner"
    actual = (
        f"previous winner={other_record.winner_nomination.nominee.full_name} "
        f"({other.cycle.cycle_key}), current winner="
        f"{record.winner_nomination.nominee.full_name if record.winner_nomination else None} "
        f"({fx.cycle.cycle_key}), votes={record.winning_votes}"
    )
    return (
        expected,
        actual,
        # Compare the months, not the primary keys: each fixture has its own
        # database, so cycle_id is 1 in both and would prove nothing.
        other.cycle.cycle_key != fx.cycle.cycle_key
        and record.winner_nomination_id == approved[2].id
        and record.winning_votes == 4,
    )


def s14_winner_email_recipient(db, fx: Fixture):
    approved = []
    for index in range(7):
        nomination = fx.nominate(index)
        if index < 2:
            fx.complete(nomination, [DECISION_APPROVE] * 4)
            approved.append(nomination)
        else:
            fx.complete(nomination, [DECISION_REJECT] * 4)
    shortlisting.run_shortlist(db, fx.cycle, actor=None)
    _votes_for(fx, voting.current_round(db, fx.cycle), [approved[1].id] * 4)

    record = winners.get_winner(db, fx.cycle)
    mail = db.scalars(
        select(NotificationLog).where(NotificationLog.template_key == "winner_announcement")
    ).all()
    winner = record.winner_nomination.nominee
    expected = f"The winner email goes to {winner.email} and to nobody else"
    actual = (
        f"recipients={[m.recipient_email for m in mail]}, "
        f"subject mentions winner={'yes' if mail and winner.full_name in mail[0].subject else 'no'}, "
        f"leaks voter names={'no' if mail and not any(m.name in mail[0].body for m in fx.final_voters()) else 'yes'}"
    )
    return (
        expected,
        actual,
        len(mail) == 1
        and mail[0].recipient_email == winner.email
        and winner.full_name in mail[0].subject
        and not any(m.name in mail[0].body for m in fx.final_voters()),
    )


def s15_unauthorised_blocked(db, fx: Fixture):
    nomination = fx.nominate(0)
    # With exactly seven members the two panels cover everyone, so add an eighth
    # member who is assigned to neither panel to act as the genuine outsider.
    not_assigned = panels.add_member(
        db, employee=fx.employee(1013), management_level="Officer", actor=None
    )
    db.flush()

    # A member who is not on this cycle's initial panel cannot review.
    review_blocked = False
    try:
        fx.review(nomination, not_assigned, DECISION_APPROVE)
    except PermissionDenied:
        review_blocked = True

    # A member who is not on the final panel cannot vote.
    for index in range(1, 7):
        fx.complete(fx.nominate(index))
    fx.complete(nomination)
    shortlisting.run_shortlist(db, fx.cycle, actor=None)
    round_ = voting.current_round(db, fx.cycle)
    candidate = voting.ballot_candidates(db, round_)[0].nomination_id
    vote_blocked = False
    try:
        voting.cast_vote(db, cycle=fx.cycle, voter=not_assigned, nomination_id=candidate, actor=None)
    except PermissionDenied:
        vote_blocked = True

    # Role enforcement through the same dependency the routes use.
    employee_user = db.scalar(select(User).where(User.email == "anele.mokoena@casidra.co.za"))
    admin_user = db.scalar(select(User).where(User.email == "admin@casidra.co.za"))
    employee_denied = False
    try:
        require_roles(SYSTEM_ADMIN)(user=employee_user)
    except Exception as exc:  # noqa: BLE001
        employee_denied = exc.__class__.__name__ == "Forbidden"
    admin_allowed = require_roles(SYSTEM_ADMIN)(user=admin_user).id == admin_user.id

    # Confidential detail is hidden from read-only management.
    from app.routers.nominations import can_view_full

    management_user = db.scalar(select(User).where(User.email == "management@casidra.co.za"))
    management_hidden = not can_view_full(db, management_user, nomination)
    hr_user = db.scalar(select(User).where(User.email == "hr@casidra.co.za"))
    hr_allowed = can_view_full(db, hr_user, nomination)

    # HTTP layer: /admin must answer 403 for a non-administrator.
    http_status_employee = http_status_admin = None
    http_note = ""
    try:
        from fastapi.testclient import TestClient

        from app.database import get_db
        from app.main import app

        def _override():
            yield db

        app.dependency_overrides[get_db] = _override
        client = TestClient(app)
        cookie = {"casidra_recognition_session": create_session_token(employee_user.id)}
        http_status_employee = client.get("/admin", cookies=cookie, follow_redirects=False).status_code
        admin_cookie = {"casidra_recognition_session": create_session_token(admin_user.id)}
        http_status_admin = client.get("/admin", cookies=admin_cookie, follow_redirects=False).status_code
    except Exception as exc:  # noqa: BLE001
        http_note = f" (http check unavailable: {exc.__class__.__name__}: {exc})"
    finally:
        try:
            from app.database import get_db
            from app.main import app

            app.dependency_overrides.pop(get_db, None)
        except Exception:  # noqa: BLE001
            pass

    expected = (
        "Unassigned reviewers and voters are refused, role checks deny non-administrators "
        "(HTTP 403 on /admin), and management cannot read confidential nomination detail"
    )
    actual = (
        f"review refused={review_blocked}, vote refused={vote_blocked}, "
        f"employee role check denied={employee_denied}, admin allowed={admin_allowed}, "
        f"management detail hidden={management_hidden}, HR detail allowed={hr_allowed}, "
        f"/admin status employee={http_status_employee}, admin={http_status_admin}{http_note}"
    )
    return (
        expected,
        actual,
        review_blocked
        and vote_blocked
        and employee_denied
        and admin_allowed
        and management_hidden
        and hr_allowed
        and http_status_employee == 403
        and http_status_admin == 200,
    )


SCENARIOS = [
    (1, "Six nominations: no shortlisting or final voting", s01_six_nominations),
    (2, "Seven nominations with one outstanding panel review: no shortlisting", s02_one_outstanding_review),
    (3, "Seven completed nominations, all Rejected: no final candidates", s03_all_rejected),
    (4, "Seven completed nominations with two Approved: only those are shortlisted", s04_only_approved_shortlisted),
    (5, "Four unique initial reviewers per nomination", s05_four_unique_reviewers),
    (6, "Exactly four initial panel members and four final voting members", s06_panel_sizes),
    (7, "Exactly one member shared between the two panels", s07_one_shared_member),
    (8, "Panel assignments unchanged after retries and additional nominations", s08_assignments_stable),
    (9, "Duplicate review or vote submissions do not inflate counts", s09_duplicates_do_not_inflate),
    (10, "Only shortlisted candidates appear in final ballots", s10_only_shortlisted_on_ballot),
    (11, "Four valid final votes trigger winner calculation", s11_four_votes_calculate_winner),
    (12, "A tie produces an escalation, not an automatic winner", s12_tie_escalates),
    (13, "Votes from other months cannot affect the current winner", s13_other_months_isolated),
    (14, "The winner email goes to the correct employee", s14_winner_email_recipient),
    (15, "Unauthorised users cannot access restricted records or actions", s15_unauthorised_blocked),
]


def run_all(persist: bool = False, actor: str | None = None) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for number, name, function in SCENARIOS:
        fx: Fixture | None = None
        try:
            fx = _fixture()
            expected, actual, passed = function(fx.db, fx)
            results.append(
                ScenarioResult(
                    id=number, name=name, expected=expected, actual=actual, passed=bool(passed)
                )
            )
        except Exception as exc:  # noqa: BLE001 - a failing scenario is a result, not a crash
            log.exception("Acceptance scenario %s failed", number)
            detail = f"{exc.__class__.__name__}: {exc}"
            results.append(
                ScenarioResult(
                    id=number,
                    name=name,
                    expected="Scenario runs without error",
                    actual="Scenario raised an exception",
                    passed=False,
                    detail=detail[:400],
                )
            )
        finally:
            if fx is not None:
                fx.db.close()

    if persist:
        _persist(results, actor)
    return results


def summarise(results: list[ScenarioResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "all_passed": total > 0 and passed == total,
    }


def _persist(results: list[ScenarioResult], actor: str | None) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        payload = {
            "ran_at": utcnow().isoformat(),
            "actor": actor or "system",
            "summary": summarise(results),
            "results": [asdict(r) for r in results],
        }
        row = db.get(SystemSetting, LAST_RUN_KEY)
        if row is None:
            db.add(
                SystemSetting(
                    key=LAST_RUN_KEY,
                    value=json.dumps(payload),
                    description="Result of the last acceptance-test run.",
                    updated_by=actor,
                )
            )
        else:
            row.value = json.dumps(payload)
            row.updated_by = actor
        db.commit()
    finally:
        db.close()


def latest_results() -> dict:
    """Return the stored run (or an empty shell) for the validation screen."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(SystemSetting, LAST_RUN_KEY)
        if row is None:
            return {"ran_at": None, "results": [], "summary": summarise([])}
        payload = json.loads(row.value)
        payload["results"] = [ScenarioResult(**r) for r in payload.get("results", [])]
        # Stored as an ISO string for JSON; hand the screen a real datetime so it
        # renders in the recognition timezone.
        try:
            payload["ran_at"] = dt.datetime.fromisoformat(payload["ran_at"]) if payload.get("ran_at") else None
        except (TypeError, ValueError):
            payload["ran_at"] = None
        return payload
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover - manual run helper
    outcome = run_all()
    for item in outcome:
        print(f"[{'PASS' if item.passed else 'FAIL'}] {item.id}. {item.name}")
        if not item.passed:
            print(f"    expected: {item.expected}")
            print(f"    actual:   {item.actual}")
    print(summarise(outcome))
