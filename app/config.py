"""Runtime configuration.

Everything is read from the environment so the same code runs in the Base44
sandbox (values from `.env.base44-defaults` overridden by the platform-managed
`/run/base44/app.env`) and in the test suite (values set by the fixtures).
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

APP_NAME = "Casidra Employee Recognition System"
APP_SHORT = "Employee Recognition"
BRAND_NAME = "Casidra"
TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Africa/Johannesburg")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        log.warning("Environment variable %s=%r is not an integer; using %s", name, raw, default)
        return default


class Settings:
    """Process-wide settings, resolved once at import time."""

    def __init__(self) -> None:
        self.database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'recognition.db'}")
        self.data_dir: Path = DATA_DIR
        self.outbox_dir: Path = Path(os.getenv("OUTBOX_DIR", DATA_DIR / "outbox"))

        # Sessions -------------------------------------------------------
        self.session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "casidra_recognition_session")
        self.session_ttl_hours: int = _int("SESSION_TTL_HOURS", 12)
        self.session_secret: str = os.getenv("SESSION_SECRET", "").strip()
        if not self.session_secret:
            # Boot must not depend on a secret being present, but a random
            # per-process key means sessions end at restart. The Base44 sandbox
            # injects a stable SESSION_SECRET through /run/base44/app.env.
            self.session_secret = secrets.token_urlsafe(48)
            self.session_secret_ephemeral = True
            log.warning(
                "SESSION_SECRET is not set — using an ephemeral key. Sessions will not "
                "survive a restart. Set SESSION_SECRET (or provide it as an app secret)."
            )
        else:
            self.session_secret_ephemeral = False

        # Email ----------------------------------------------------------
        self.notification_transport: str = os.getenv("NOTIFICATION_TRANSPORT", "auto").strip().lower()
        self.smtp_host: str = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port: int = _int("SMTP_PORT", 587)
        self.smtp_username: str = os.getenv("SMTP_USERNAME", "").strip()
        self.smtp_password: str = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from: str = os.getenv("SMTP_FROM", "recognition@casidra.co.za").strip()
        self.smtp_use_tls: bool = _flag("SMTP_USE_TLS", True)
        self.smtp_timeout: int = _int("SMTP_TIMEOUT", 10)

        # Workflow -------------------------------------------------------
        self.enable_scheduler: bool = _flag("ENABLE_SCHEDULER", False)
        self.seed_default_password: str = os.getenv("SEED_DEFAULT_PASSWORD", "Casidra#2026")

        # Sandbox --------------------------------------------------------
        # BASE44_PREVIEW_MODE is supplied by the Base44 platform in the sandbox.
        # It only ever turns on development conveniences (e.g. showing the seed
        # account list on the sign-in screen) — never a security bypass.
        self.preview_mode: bool = os.getenv("BASE44_PREVIEW_MODE") == "1"
        self.public_host_suffix: str = os.getenv("BASE44_PUBLIC_HOST_SUFFIX", "")
        self.sandbox_host_domain: str = os.getenv("BASE44_SANDBOX_HOST_DOMAIN", "")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def smtp_configured(self) -> bool:
        if self.notification_transport == "outbox":
            return False
        return bool(self.smtp_host)


settings = Settings()
