# Working in this repository

## What this repo is

A collection of 12 standalone Python learning scripts at the repo root
(`HelloWorld.py`, `Menu.py`, `shopping.py`, …). They are interactive CLI
programs: they read answers with `input()` and print results. There is **no
web application, no package manifest, and no third-party dependency** — only
the Python standard library.

## The preview surface (read this first)

The sandbox preview can only display a web page served on port 3000, and CLI
scripts have no web entry point. `app/` therefore holds a small runner that
makes the scripts visible and runnable in the preview:

- `app/main.py` — a hand-written ASGI app (stdlib only). It discovers `*.py` at
  the repo root, counts each script's `input()` calls to know how many answers
  it needs, and runs a selected script in a subprocess, feeding the answers on
  stdin and returning stdout/stderr/exit code as JSON.
- `app/static/index.html` — the single-page UI (script list, source view,
  answer fields, output).

Endpoints: `GET /` (UI), `GET /api/scripts`, `POST /api/run`.

This runner is **only** a viewer/executor. It does not modify the scripts, and
the scripts themselves are the project.

## Running it

```bash
docker compose -f docker-compose.base44.yml up -d --build
```

- Single service `web`: `python:3.12-slim`, source bind-mounted at `/app`,
  dependencies installed on startup from `requirements.txt`, uvicorn with
  `--reload` (so edits to scripts or the runner apply without a rebuild).
- Web entry point on host port 3000. Healthcheck curls `/` with Python's
  `urllib` (the slim image has no `curl`).
- No database, cache, queue, or external service. **No credentials are
  required**, and `.base44/environment.json` declares no secrets.

## Notes / quirks

- Adding a new `*.py` at the repo root makes it appear in the preview
  automatically; no registration needed.
- Several scripts contain logic bugs/oddities that are part of the original
  coursework (e.g. `baby.py` compares a birth year against `18`, and
  `manipulation.py` uses hard-coded slice indices). Do not "fix" them unless
  asked — output changes would misrepresent the exercises.
- `POST /api/run` only accepts top-level `*.py` names; path traversal is
  rejected.
- Scripts that need more answers than supplied block on `input()`; the runner
  kills them after 10s and reports it.

## Verifying it works

```bash
curl -s localhost:3000/ | head -5
curl -s localhost:3000/api/scripts
curl -s -X POST localhost:3000/api/run \
  -H 'content-type: application/json' \
  -d '{"name":"HelloWorld.py","inputs":["Ada","36"]}'
# → {"stdout":"Enter your name: Enter your age: Hi Ada You are 36 years old.\nHello World\n", ...}
```
