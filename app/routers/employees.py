"""Employee directory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ConflictError, ValidationError
from app.models import MANAGEMENT_LEVELS, Employee, PanelMember, User
from app.roles import HR_ROLES
from app.security import get_current_user, require_roles, require_user
from app.services import audit
from app.timeutil import utcnow
from app.web import clean, redirect_with, render

router = APIRouter(prefix="/employees")


def _directory(db: Session, search: str, department: str, level: str, status: str) -> list[Employee]:
    query = select(Employee)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(Employee.first_name).like(term),
                func.lower(Employee.last_name).like(term),
                func.lower(Employee.email).like(term),
                func.lower(Employee.employee_number).like(term),
                func.lower(Employee.job_title).like(term),
            )
        )
    if department:
        query = query.where(Employee.department == department)
    if level:
        query = query.where(Employee.management_level == level)
    if status == "active":
        query = query.where(Employee.is_active.is_(True))
    elif status == "inactive":
        query = query.where(Employee.is_active.is_(False))
    return list(db.scalars(query.order_by(Employee.last_name, Employee.first_name)))


@router.get("")
def list_employees(
    request: Request,
    q: str | None = None,
    department: str | None = None,
    level: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    employees = _directory(db, clean(q), clean(department), clean(level), clean(status))
    departments = [
        row for row in db.scalars(select(Employee.department).distinct().order_by(Employee.department)).all() if row
    ]
    panel_ids = {
        row for row in db.scalars(select(PanelMember.employee_id).where(PanelMember.is_active.is_(True))).all()
    }
    return render(
        request,
        "employees.html",
        {
            "page_title": "Employee Directory",
            "employees": employees,
            "departments": departments,
            "levels": MANAGEMENT_LEVELS,
            "panel_ids": panel_ids,
            "filters": {
                "q": clean(q),
                "department": clean(department),
                "level": clean(level),
                "status": clean(status),
            },
            "can_manage": user.has_role(*HR_ROLES),
        },
        user=user,
    )


@router.post("")
async def create_employee(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    form = await request.form()
    number = clean(form.get("employee_number"))
    first = clean(form.get("first_name"))
    last = clean(form.get("last_name"))
    email = clean(form.get("email")).lower()
    department = clean(form.get("department")) or "Unassigned"
    job_title = clean(form.get("job_title"))
    level = clean(form.get("management_level")) or MANAGEMENT_LEVELS[-1]

    errors = {}
    if not number:
        errors["employee_number"] = "Employee number is required."
    if not first:
        errors["first_name"] = "First name is required."
    if not last:
        errors["last_name"] = "Last name is required."
    if "@" not in email:
        errors["email"] = "A valid email address is required."
    if level not in MANAGEMENT_LEVELS:
        errors["management_level"] = "Select a valid management level."
    if errors:
        return redirect_with("/employees", err=" ".join(errors.values()))

    employee = Employee(
        employee_number=number,
        first_name=first,
        last_name=last,
        email=email,
        department=department,
        job_title=job_title,
        management_level=level,
        is_active=True,
    )
    db.add(employee)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return redirect_with(
            "/employees", err="An employee with that employee number or email already exists."
        )

    audit.record(
        db,
        event_type="EMPLOYEE_CREATED",
        summary=f"Employee {employee.full_name} ({employee.employee_number}) added to the directory",
        actor=user,
        entity_type="employee",
        entity_id=employee.id,
    )
    db.commit()
    return redirect_with("/employees", ok=f"{employee.full_name} added to the directory.")


@router.post("/{employee_id}/update")
async def update_employee(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    employee = db.get(Employee, employee_id)
    if employee is None:
        return redirect_with("/employees", err="Employee not found.")
    form = await request.form()
    before = {
        "department": employee.department,
        "job_title": employee.job_title,
        "management_level": employee.management_level,
    }
    employee.department = clean(form.get("department")) or employee.department
    employee.job_title = clean(form.get("job_title")) or employee.job_title
    level = clean(form.get("management_level"))
    if level in MANAGEMENT_LEVELS:
        employee.management_level = level
    employee.updated_at = utcnow()
    db.flush()

    panel = db.scalar(select(PanelMember).where(PanelMember.employee_id == employee.id))
    if panel is not None:
        panel.management_level = employee.management_level
        panel.name = employee.full_name
        panel.email = employee.email

    audit.record(
        db,
        event_type="EMPLOYEE_UPDATED",
        summary=f"{employee.full_name} record updated",
        actor=user,
        entity_type="employee",
        entity_id=employee.id,
        details={
            "before": before,
            "after": {
                "department": employee.department,
                "job_title": employee.job_title,
                "management_level": employee.management_level,
            },
        },
    )
    db.commit()
    return redirect_with("/employees", ok=f"{employee.full_name} updated.")


@router.post("/{employee_id}/toggle")
def toggle_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    employee = db.get(Employee, employee_id)
    if employee is None:
        return redirect_with("/employees", err="Employee not found.")
    employee.is_active = not employee.is_active
    employee.updated_at = utcnow()
    db.flush()
    audit.record(
        db,
        event_type="EMPLOYEE_ACTIVATED" if employee.is_active else "EMPLOYEE_DEACTIVATED",
        summary=f"{employee.full_name} marked {'active' if employee.is_active else 'inactive'}",
        actor=user,
        entity_type="employee",
        entity_id=employee.id,
    )
    db.commit()
    return redirect_with(
        "/employees",
        ok=f"{employee.full_name} is now {'active' if employee.is_active else 'inactive'}.",
    )
