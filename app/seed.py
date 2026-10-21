"""Seed data.

Creates the seven-member master Recognition Panel named in the specification,
a directory of employees, one account per role, and (optionally) a partially
completed demonstration month so the screens are not empty on first run.

Nothing here is destructive: seeding only inserts rows that are missing.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import (
    DECISION_APPROVE,
    DECISION_REJECT,
    LEVEL_EXECUTIVE,
    LEVEL_GENERAL,
    LEVEL_MANAGER,
    LEVEL_OFFICER,
    LEVEL_SPECIALIST,
    Employee,
    PanelMember,
    PanelReview,
    User,
)
from app.roles import (
    EMPLOYEE,
    FINAL_PANEL,
    HR_ADMIN,
    INITIAL_PANEL,
    MANAGEMENT,
    SYSTEM_ADMIN,
)
from app.security import hash_password
from app.services import cycles, panels
from app.timeutil import utcnow

PANEL_SEED = [
    ("CAS-1001", "Bronwyn", "Govender", LEVEL_EXECUTIVE, "Executive Office", "Executive Manager"),
    ("CAS-1002", "David", "Nefdt", LEVEL_EXECUTIVE, "Executive Office", "Executive Manager"),
    ("CAS-1003", "Keith", "Du Plessis", LEVEL_EXECUTIVE, "Executive Office", "Executive Manager"),
    ("CAS-1004", "Experience", "Matshidiso", LEVEL_MANAGER, "Operations", "Operations Manager"),
    ("CAS-1005", "Jacques", "Swanepoel", LEVEL_MANAGER, "Finance", "Finance Manager"),
    ("CAS-1006", "Loinice", "Seconds", LEVEL_MANAGER, "Human Resources", "HR Manager"),
    ("CAS-1007", "Michael", "Mackenzie", LEVEL_MANAGER, "Information Technology", "IT Manager"),
]

OTHER_SEED = [
    ("CAS-1000", "Adrian", "Petersen", LEVEL_MANAGER, "Information Technology", "Systems Manager"),
    ("CAS-1008", "Nadia", "Fourie", LEVEL_MANAGER, "Human Resources", "Recognition Administrator"),
    ("CAS-1009", "Gerhard", "Louw", LEVEL_EXECUTIVE, "Executive Office", "Chief Operating Officer"),
    ("CAS-1010", "Anele", "Mokoena", LEVEL_SPECIALIST, "Operations", "Operations Specialist"),
    ("CAS-1011", "Thandiwe", "Nkosi", LEVEL_OFFICER, "Finance", "Financial Officer"),
    ("CAS-1012", "Pieter", "van Wyk", LEVEL_SPECIALIST, "Information Technology", "Systems Analyst"),
    ("CAS-1013", "Lerato", "Dlamini", LEVEL_OFFICER, "Human Resources", "HR Officer"),
    ("CAS-1014", "Sipho", "Ndlovu", LEVEL_SPECIALIST, "Field Services", "Field Specialist"),
    ("CAS-1015", "Chantelle", "Adams", LEVEL_OFFICER, "Communications", "Communications Officer"),
    ("CAS-1016", "Riaan", "Botha", LEVEL_SPECIALIST, "Field Services", "Field Specialist"),
    ("CAS-1017", "Nomsa", "Khumalo", LEVEL_GENERAL, "Facilities", "Facilities Assistant"),
    ("CAS-1018", "Johan", "Steyn", LEVEL_OFFICER, "Information Technology", "Support Officer"),
    ("CAS-1019", "Zanele", "Mahlangu", LEVEL_SPECIALIST, "Human Resources", "Learning Specialist"),
    ("CAS-1020", "Elmarie", "Coetzee", LEVEL_OFFICER, "Communications", "Stakeholder Officer"),
]

DEMO_NOMINATIONS = [
    {
        "nominator": "CAS-1010",
        "nominee": "CAS-1014",
        "description": (
            "Coordinated the emergency repairs at the Worcester depot over a public holiday weekend, "
            "keeping the site operational and safe for the Monday shift."
        ),
        "motivation": (
            "Sipho gave up his long weekend without being asked, kept every stakeholder informed and "
            "made sure no colleague worked alone. His follow-through reflects exactly the standard of "
            "care we want to recognise."
        ),
        "reviews": [DECISION_APPROVE, DECISION_APPROVE, DECISION_APPROVE, DECISION_REJECT],
    },
    {
        "nominator": "CAS-1011",
        "nominee": "CAS-1018",
        "description": (
            "Rebuilt the month-end reconciliation workbook, cutting the finance close from three days "
            "to a single afternoon and removing a recurring source of errors."
        ),
        "motivation": (
            "Johan noticed a problem nobody had asked him to fix, taught the finance team how the new "
            "workbook works and documented it so the improvement lasts beyond his own effort."
        ),
        "reviews": [DECISION_APPROVE, DECISION_REJECT, DECISION_REJECT, DECISION_REJECT],
    },
    {
        "nominator": "CAS-1012",
        "nominee": "CAS-1019",
        "description": (
            "Designed and delivered the new frontline service training, which 42 colleagues have now "
            "completed with consistently strong feedback."
        ),
        "motivation": (
            "Zanele turned a vague request into a practical programme, ran the sessions herself and "
            "followed up individually with every participant. She deserves recognition for the "
            "difference in service quality."
        ),
        "reviews": [DECISION_APPROVE, DECISION_APPROVE],
    },
]


def _email(first: str, last: str) -> str:
    return f"{first.lower()}.{last.lower().replace(' ', '')}@casidra.co.za"


def _get_employee(db: Session, number: str) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.employee_number == number))


def _ensure_employee(db: Session, row) -> Employee:
    number, first, last, level, department, title = row
    employee = _get_employee(db, number)
    if employee is not None:
        return employee
    employee = Employee(
        employee_number=number,
        first_name=first,
        last_name=last,
        email=_email(first, last),
        department=department,
        job_title=title,
        management_level=level,
        is_active=True,
    )
    db.add(employee)
    db.flush()
    return employee


def _ensure_user(db: Session, *, employee: Employee | None, email: str, name: str, roles: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    user = User(
        email=email,
        full_name=name,
        password_hash=hash_password(password),
        roles=roles,
        employee_id=employee.id if employee else None,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def seed_people(db: Session) -> dict:
    password = app_settings.seed_default_password
    created = {"employees": 0, "panel_members": 0, "users": 0}

    before = db.scalar(select(func.count(Employee.id))) or 0

    panel_employees = []
    for row in PANEL_SEED:
        employee = _ensure_employee(db, row)
        panel_employees.append(employee)
    for row in OTHER_SEED:
        _ensure_employee(db, row)

    for employee, row in zip(panel_employees, PANEL_SEED):
        member = db.scalar(select(PanelMember).where(PanelMember.employee_id == employee.id))
        if member is None:
            db.add(
                PanelMember(
                    employee_id=employee.id,
                    name=employee.full_name,
                    email=employee.email,
                    management_level=row[3],
                    is_active=True,
                )
            )
            db.flush()

    _ensure_user(
        db,
        employee=_get_employee(db, "CAS-1000"),
        email="admin@casidra.co.za",
        name="Adrian Petersen",
        roles=SYSTEM_ADMIN,
        password=password,
    )
    _ensure_user(
        db,
        employee=_get_employee(db, "CAS-1008"),
        email="hr@casidra.co.za",
        name="Nadia Fourie",
        roles=HR_ADMIN,
        password=password,
    )
    _ensure_user(
        db,
        employee=_get_employee(db, "CAS-1009"),
        email="management@casidra.co.za",
        name="Gerhard Louw",
        roles=MANAGEMENT,
        password=password,
    )

    for employee in panel_employees:
        _ensure_user(
            db,
            employee=employee,
            email=employee.email,
            name=employee.full_name,
            roles=f"{INITIAL_PANEL},{FINAL_PANEL}",
            password=password,
        )

    for number in ("CAS-1010", "CAS-1011", "CAS-1012", "CAS-1013"):
        employee = _get_employee(db, number)
        _ensure_user(
            db,
            employee=employee,
            email=employee.email,
            name=employee.full_name,
            roles=EMPLOYEE,
            password=password,
        )

    db.flush()
    created["employees"] = (db.scalar(select(func.count(Employee.id))) or 0) - before
    created["panel_members"] = db.scalar(select(func.count(PanelMember.id))) or 0
    created["users"] = db.scalar(select(func.count(User.id))) or 0
    return created


def seed_demo_month(db: Session) -> dict:
    """Create a partially completed current month so the workflow is visible."""
    cycle = cycles.current_cycle(db)
    if cycle.panels_assigned_at is None:
        panels.assign_panels(db, cycle, None)
    db.flush()

    from app.services import nominations as nomination_service
    from app.services import reviews as review_service

    existing = db.scalar(select(func.count()).select_from(nomination_service.Nomination)) or 0
    if existing:
        db.commit()
        return {"created": 0, "cycle": cycle.cycle_key}

    initial = panels.members_for(db, cycle, "INITIAL")
    created = 0
    for index, spec in enumerate(DEMO_NOMINATIONS):
        nominator = _get_employee(db, spec["nominator"])
        nominee = _get_employee(db, spec["nominee"])
        nomination = nomination_service.submit_nomination(
            db,
            actor=None,
            cycle=cycle,
            nominee=nominee,
            nominator=nominator,
            department=nominee.department,
            achievement_date=dt.date.today() - dt.timedelta(days=10 + index),
            achievement_description=spec["description"],
            motivation=spec["motivation"],
        )
        created += 1
        for reviewer, decision in zip(initial, spec["reviews"]):
            review_service.submit_review(
                db,
                nomination=nomination,
                reviewer=reviewer,
                decision=decision,
                comments=(
                    "Verified against the team's records."
                    if decision == DECISION_APPROVE
                    else "Insufficient evidence supplied for the claim made."
                ),
                actor=None,
            )
    db.commit()
    return {"created": created, "cycle": cycle.cycle_key, "seeded_at": utcnow().isoformat()}
