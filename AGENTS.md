# Working in this repository

## What is here

Two things live in this repo, and they are unrelated:

1. **The root `*.py` scripts** (`HelloWorld.py`, `Menu.py`, `shopping.py`, …) — the
   original 12 interactive Python coursework scripts. Standard library only,
   not part of the web application. Do not modify them (see "Quirks").
2. **`prototype/`** — the Casidra *Arrivals & Departures* design prototype: a
   premium enterprise UI for an employee onboarding (arrivals) system, built to
   be lifted into an existing Python/Django application.

`prototype/` is a **design prototype only**. It is deliberately plain HTML,
CSS and vanilla JavaScript with **no build step, no framework and no
dependency**, so the markup maps one-to-one onto Django templates.

## Running it

```bash
docker compose -f docker-compose.base44.yml up -d --build
```

- Single service `web`: `python:3.12-slim`, source bind-mounted at `/app`,
  running `python prototype/server.py` on host port **3000**.
- No database, cache, queue or external service. **No credentials**, no
  migrations, no seed step.
- Healthcheck curls `/` with Python's `urllib` (the slim image has no `curl`)
  and asserts the page contains "Casidra".

## The dev server (`prototype/server.py`)

Standard library only. It does three things worth knowing:

1. **Server-side includes.** Any `<!-- @include partials/x.html -->` comment in
   a served `.html` file is expanded from `prototype/` at request time, up to 5
   levels deep. This is how the shell (`partials/sidebar.html`,
   `partials/topbar.html`, `partials/icons.html`, `partials/shell-end.html`),
   the head assets and the shared new-case form are kept in one place —
   the same split Django will use with `{% include %}`.
   **Quirk:** because the includes are expanded by the server, opening a page
   straight off disk in a browser leaves the include comments unexpanded. Always
   view pages through port 3000.
2. **Live reload.** `/__reload` is a Server-Sent Events stream that watches the
   prototype tree and tells the browser to reload on any change. Every page
   subscribes via `assets/js/app.js`. No restart is needed after an edit.
3. **No caching.** Every response is `Cache-Control: no-store`.

The server binds `0.0.0.0` and applies **no host or origin allowlist**, so no
preview-host or CORS configuration is required and no `BASE44_PREVIEW_MODE`
override exists anywhere in this branch. If a host allowlist is ever introduced,
extend it with the wildcard `.$BASE44_SANDBOX_HOST_DOMAIN`, never an exact host.

## Files

| Path | Purpose |
| --- | --- |
| `prototype/index.html` | Onboarding dashboard (`/`) — KPIs, case table, approvals, upcoming starts |
| `prototype/cases.html` | All onboarding cases — filters, urgency tabs, pagination |
| `prototype/case.html` | Employee case file — stage strip, timeline, HR/IT/Facilities/Communications checklists, add-task form |
| `prototype/tasks.html` | Cross-case task queue — department/owner/status filters, row approvals |
| `prototype/design-system.html` | Tokens, components, accessibility notes, Django mapping |
| `prototype/partials/` | Shared shell, icon sprite, head assets, new-case sheet |
| `prototype/assets/css/tokens.css` | **Single source of truth** for colour, type, space, radius, elevation, motion |
| `prototype/assets/css/base.css` | Reset, document defaults, accessibility primitives, utilities |
| `prototype/assets/css/layout.css` | App shell (sidebar, topbar, content), grids, breakpoints |
| `prototype/assets/css/components.css` | Buttons, badges, cards, KPIs, progress, timeline, tables, forms, menus, dialogs, toasts, empty states … |
| `prototype/assets/css/design-system.css` | Design-system page furniture only — never used by product screens |
| `prototype/assets/js/app.js` | The whole interaction layer (vanilla, no dependencies) |

## Adding a page

Copy any page's skeleton, then:

- include `partials/head-assets.html` in `<head>` and give the page its own
  `<title>`/description;
- include `partials/icons.html`, `partials/sidebar.html` at the top of `<body>`,
  `partials/topbar.html` inside `.app__body`, and `partials/shell-end.html` +
  `partials/scripts.html` at the end;
- set `<body class="app" data-page="…">`. `app.js` matches `data-page` against
  `data-nav` on the sidebar links to set `is-active` and `aria-current="page"`.
  This replaces Django's `{% if active == 'dashboard' %}` logic — keep it in one
  place.

## Component contracts in `app.js`

These data attributes are the API between markup and behaviour. Reuse them
instead of writing new JavaScript:

- **Droppable menu** — `[data-menu]` + `[data-menu-trigger]` + `[data-menu-panel]`.
- **Filterable table** — `[data-table-region]` wrapping `[data-table-search]`,
  `[data-table-filter="key"]` selects, `<tbody data-table-rows>` whose rows carry
  `data-search` and one `data-<key>` per filter, optional `[data-table-group]`
  segmented buttons with `data-group-value` matching a row's `data-group`,
  optional `[data-table-wrap]`, `[data-table-empty]`, `[data-table-count]` and
  `[data-table-reset]`. `data-count-noun` sets the word used in the count line.
- **Checklist section** — `[data-checklist][data-department="hr|it|facilities|comms"]`
  containing `[data-task-row]`s with a `.task__box` checkbox and a
  `[data-task-status]` badge. Section progress (`[data-section-count]`,
  `[data-section-fill]`, `[data-section-value]`) and the case-level donut
  (`[data-overall-*]`) are recomputed from the rendered rows.
- **Confirmation dialog** — one shared `<dialog>` in `partials/shell-end.html`.
  Call `window.casidraPrototype.confirm({title, sub, body, confirmLabel, icon,
  tone, askComment, onConfirm})`; do not add page-specific dialogs.
- **Sheets (forms)** — `[data-sheet-open="id"]` opens; the form declares
  `data-sheet-form="handler"` and `app.js` dispatches through its
  `SHEET_HANDLERS` registry (`new-case`, `add-task`). Fields opt into validation
  with `data-validate` (+ `required`, `data-required-message`, `data-min-date`).
  `handleAddTask` clones `<template id="task-template">` from `case.html`.
- **Prototype toasts** — any element with `data-toast="Title"` plus optional
  `data-toast-message` / `data-toast-tone` shows a toast instead of navigating.
  Used for anything the prototype deliberately does not implement.
- **Status tones** — `badge--ok` (on track / complete), `badge--warn` (at risk /
  awaiting approval), `badge--danger` (overdue / blocked), `badge--info`
  (in progress), neutral `badge` (not started). Progress fills mirror these via
  `progress__fill--ok|warn|danger`.

## Non-negotiable rules for this prototype

- **Nothing is saved.** There is no backend call anywhere in `prototype/`.
  Every toast, dialog and empty state must keep saying so. Never describe
  authentication, permissions, approvals, persistence or email delivery as
  implemented — they are design only.
- **Fictional sample data only.** Keep names, dates and departments consistent
  across pages (Amara Okafor's case is `ONB-2026-0148`: 19 tasks, 9 complete,
  47% ready, starting Tue 3 Nov 2026). The dashboard shows 8 recent cases of 12;
  the task queue lists 17 tasks (4 overdue, 9 due soon, 4 complete). If you
  change one of these numbers, change it everywhere.
- **Accessibility is part of the design**: visible labels, `aria-invalid` and
  `aria-describedby` on invalid fields, `role="alert"` form summaries, status
  text beside every status colour, `aria-current` on active nav and steps, and
  the skip link. Contrast pairs are documented on the design-system page.
- **Reuse before adding.** New patterns belong in `components.css` and on
  `design-system.html` so offboarding can inherit them.

## Verifying it works

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:3000/            # 200
curl -s localhost:3000/ | grep -c 'unresolved include'              # 0
for p in index.html cases.html case.html tasks.html design-system.html; do
  curl -s -o /dev/null -w "$p %{http_code}\n" "localhost:3000/$p"
done
```

In the browser, the flows worth exercising: dashboard table filter → empty
state → reset; `New onboarding case` → submit empty (6 validation errors) → fill
→ confirmation dialog → toast; case page → tick a checklist box (section and
case progress update) → `Approve` a step → `Request changes` with a comment →
`Add task` → `Mark ready for day one` (blocked while tasks are open); task queue
→ urgency tabs and row approvals. All verified with the preview tools; there is
no automated test suite in this repo.

## Quirks

- The root `*.py` scripts are original coursework and contain deliberate
  logic oddities. Leave them and their output alone.
- Pages are flat in `prototype/`, so relative links (`assets/…`, `case.html`)
  work from any page. Keep new pages flat too.
- `partials/icons.html` is an inline SVG sprite; icons are used as
  `<svg class="icon"><use href="#i-name"/></svg>`. Self-closing `<use/>` is
  valid inside SVG content — do not "fix" it.
- Google Fonts (Inter) is a progressive enhancement; `tokens.css` declares the
  full system fallback stack, so the prototype looks correct offline.
