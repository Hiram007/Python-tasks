"""FastAPI application entry point for the Casidra Employee Recognition System.

The application is server-rendered: every screen is a Jinja template rendered by
one of the routers in `app.routers`, and all authorisation is decided on the
server (see `app.security`). Static assets live in `app/static`.

Run in development with:
    python -m app.bootstrap && uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import APP_NAME, BASE_DIR, settings
from app.routers import (
    admin,
    auth,
    comms,
    dashboard,
    employees,
    governance,
    nominations,
    panel,
    reviews,
    selection,
)
from app.web import render

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the scheduled shortlisting/reminder jobs when configured to."""
    if settings.enable_scheduler:
        from app import scheduler

        scheduler.start()
        log.info("Automatic shortlisting and reminder jobs enabled.")
    else:
        log.info("Scheduler disabled (ENABLE_SCHEDULER is not set).")
    try:
        yield
    finally:
        if settings.enable_scheduler:
            from app import scheduler

            scheduler.shutdown()


app = FastAPI(
    title=APP_NAME,
    description="Employee of the Month nomination, panel review, shortlisting, voting and audit workflow.",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")

# Order is not significant: every router declares its own distinct prefix.
for module in (auth, dashboard, employees, nominations, panel, reviews, selection, comms, governance, admin):
    app.include_router(module.router)


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    """Render branded error pages; leave redirects (303) to the default handler."""
    if exc.status_code in (403, 404):
        return render(
            request,
            "error.html",
            {
                "page_title": "Access denied" if exc.status_code == 403 else "Page not found",
                "status_code": exc.status_code,
                "message": exc.detail if isinstance(exc.detail, str) else "",
            },
            user=None,
            status_code=exc.status_code,
        )
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    """Render the branded error page for unexpected failures instead of a bare 500."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return render(
        request,
        "error.html",
        {
            "page_title": "Something went wrong",
            "status_code": 500,
            "message": "The request could not be completed. The error has been logged for an administrator.",
        },
        user=None,
        status_code=500,
    )
