# Casidra Employee Recognition System — working notes

FastAPI + SQLAlchemy application rendering Jinja2 templates. All authorisation
is enforced on the server (`app/security.py`, `app/roles.py`); the UI only hides
what the server would refuse anyway. Run it with the Base44 compose file — see
`docker-compose.base44.yml` for the executable runbook.

## Things that are not obvious

**The repository root is not on the import path, on purpose.** The root also
holds a set of standalone practice scripts (`HelloWorld.py`, `numbers.py`,
`shopping.py`, …) that must stay frozen. `numbers.py` shadows the standard
library's `numbers` module, which SQLAlchemy imports, so running the app with
the repository root on `sys.path` fails at import. The compose `web` service
therefore runs from `/opt/casidra`, a shim directory containing only a symlink
to the `app` package. Do not "fix" this by moving or renaming the practice
scripts, and do not run uvicorn with `--app-dir` pointed at the repository root.

**The schema and seed data are created on every start** by
`python -m app.bootstrap`, which runs before uvicorn. It is idempotent and
non-destructive: it only inserts rows that are missing, then (unless
`SEED_DEMO_MONTH=0`) builds a partially completed current month so the screens
are not empty. PostgreSQL is the database; there are no migrations — the schema
comes from the SQLAlchemy models.

**`SESSION_SECRET` must be set for sessions to survive a restart.** Without it
`app/config.py` falls back to a random per-process key, so every `--reload`
restart signs everyone out. The sandbox receives a generated placeholder through
`/run/base44/app.env`. The value is never read from `.env.base44-defaults`
(which leaves it blank so the platform value always wins).

**Email delivery is honest by design.** With no `SMTP_HOST`, every message is
written to the outbox directory and recorded as `UNSENT` with the reason
attached — nothing is ever reported as delivered. Set `SMTP_HOST` (or provide
SMTP credentials as app secrets) to send real mail. `NOTIFICATION_TRANSPORT`
(`auto` | `smtp` | `outbox`) is also editable on the System Administration
screen.

**`BASE44_PREVIEW_MODE`** only adds a development convenience: the seeded
account list on the sign-in screen. It is never an authentication bypass. Read
it through `settings.preview_mode` (exact string comparison with `"1"`).

**Every module screen composes the same page body.** `_macros.html` owns the
shared pattern: `page_head(title, subtitle, cycle_options, cycle_key, cycle_path)`
renders the header plus its right-hand actions (and the recognition-month picker
when a `cycle_path` is given), and `toolbar(action)` renders the filter bar. Use
`{% call %}` with either when the right side is bespoke (see `admin.html`,
`validation.html`) and `rich_subtitle=` when the subtitle carries markup (see
`dashboard.html`). `empty(title, hint, action_href, action_label)` takes an
optional call to action. Add a screen by composing these rather than
hand-writing `<div class="page-head">`, so headers, filter bars, card grids and
empty states cannot drift apart.

## Verifying a change

The acceptance suite is the single source of truth for the business rules and
drives the real service layer against an isolated in-memory database:

```bash
docker compose -f docker-compose.base44.yml exec -T web \
  sh -ec 'cd /opt/casidra && python -m pytest /app/tests -q'
```

The same 15 scenarios run from the Validation screen (HR/admin only), so the
screen and CI cannot drift apart. Note the `cd /opt/casidra` — pytest must run
with the repository root off `sys.path` for the reason above.

`python -m app.acceptance` prints a readable per-scenario report.

Sign in with a seeded account to exercise the screens by hand; the password is
`SEED_DEFAULT_PASSWORD` (see `.env.base44-defaults`). `hr@casidra.co.za` sees
every screen, `admin@casidra.co.za` additionally owns settings and panel
re-draws, and the panel members' own addresses hold the panel roles.
