"""Start-up bootstrap: create the schema, seed settings and demo data.

Run as `python -m app.bootstrap` from the container command. It is idempotent and
safe to run on every start.
"""

from __future__ import annotations

import logging
import os
import time

from sqlalchemy import func, select

from app.database import SessionLocal, create_all, engine
from app.models import Employee, PanelMember, User
from app.seed import seed_demo_month, seed_people
from app.services import settings_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bootstrap")


def wait_for_database(attempts: int = 30, delay: float = 2.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return
        except Exception as exc:  # noqa: BLE001 - any connection error means "not ready yet"
            if attempt == attempts:
                raise
            log.info("Database not ready (%s); retrying in %.0fs", exc.__class__.__name__, delay)
            time.sleep(delay)


def main() -> None:
    wait_for_database()
    create_all()
    log.info("Schema ready on %s", engine.url.render_as_string(hide_password=True))

    db = SessionLocal()
    try:
        settings_service.seed_defaults(db)
        people = seed_people(db)
        db.commit()
        log.info(
            "Directory: %s employee(s), %s panel member(s), %s user account(s)",
            db.scalar(select(func.count(Employee.id))),
            db.scalar(select(func.count(PanelMember.id))),
            db.scalar(select(func.count(User.id))),
        )
        if os.getenv("SEED_DEMO_MONTH", "1") == "1":
            result = seed_demo_month(db)
            log.info("Demonstration month: %s", result)
    finally:
        db.close()

    log.info("Bootstrap complete.")


if __name__ == "__main__":
    main()
