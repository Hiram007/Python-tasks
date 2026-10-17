# Working in this repository

## What is here

Two things live in this repo, and they are unrelated:

1. **The root `*.py` scripts** (`HelloWorld.py`, `Menu.py`, `shopping.py`, …) — the
   original 12 interactive Python coursework scripts. Standard library only,
   not part of the web application. Do not modify them (see "Quirks").
2. **`prototype/`** — the Casidra *Arrivals & Departures* design prototype: the
   complete enterprise UI for the employee lifecycle, from onboarding through
   employment administration to offboarding, built to be lifted into an existing
   Python/Django application.

`prototype/` is a **design prototype only**. It is deliberately plain HTML,
CSS and vanilla JavaScript with **no build step, no framework and no
dependency**, so the markup maps one-to-one onto Django templates.

**The prototype is not a replacement system.** Casidra's existing Django
application stays the production system of record. Nothing in `prototype/`
calls Base44 services, a backend or a third party at runtime, and no feature
described here is implemented — screens are design, not functionality.

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
   the head assets and the two form sheets are kept in one place — the same
   split Django will use with `{% include %}`.
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
| `prototype/index.html` | Dashboard (`/`) — role-scoped panels, KPIs, case table, approvals, upcoming dates |
| `prototype/directory.html` | Employee directory — register, filters, department headcount, data-quality exceptions |
| `prototype/employee.html` | Employee lifecycle record — summary, history, related tasks/approvals/assets, restricted panel |
| `prototype/cases.html` | Onboarding cases — filters, urgency tabs, pagination |
| `prototype/case.html` | Onboarding case file — stage strip, timeline, four departmental checklists, add-task sheet |
| `prototype/tasks.html` | Task queues — cross-case queue, my tasks, department queues summary |
| `prototype/offboarding.html` | Departure cases — clearance progress, outstanding work, departure calendar |
| `prototype/departure.html` | Departure case file — clearance stages, clearance checklists, asset returns, final clearance summary |
| `prototype/approvals.html` | Approval inbox — pending queue, decision detail, delegation, approval history |
| `prototype/equipment.html` | Equipment register, handover & returns, asset history, custody by department |
| `prototype/notifications.html` | Notification centre, preferences, administrative delivery configuration |
| `prototype/workflows.html` | Workflow templates — library, task sequence, transitions, escalation, versioning |
| `prototype/reports.html` | Reports & exports — performance charts, report catalogue, permission and confidentiality indicators |
| `prototype/audit.html` | Audit trail — lifecycle, approval, task and administrative events, retention rules |
| `prototype/admin-users.html` | Users, roles & permissions — accounts, permission matrix, departments, identity mapping |
| `prototype/admin-system.html` | System settings — operational status, Entra ID SSO/MFA, operational rules, security, maintenance |
| `prototype/design-system.html` | Tokens, components, system patterns, accessibility notes, Django mapping |
| `prototype/handover.html` | Implementation handover — pages, components, workflows, simulated behaviour, outstanding items |
| `prototype/partials/` | Shared shell (sidebar, topbar, icons, head assets, shell-end) and the three form sheets |
| `prototype/assets/css/tokens.css` | **Single source of truth** for colour, type, space, radius, elevation, motion |
| `prototype/assets/css/base.css` | Reset, document defaults, accessibility primitives, utilities |
| `prototype/assets/css/layout.css` | App shell (sidebar, topbar, content), grids, breakpoints |
| `prototype/assets/css/components.css` | Buttons, badges, cards, KPIs, progress, timeline, tables, forms, dialogs, toasts, charts, configuration rows … |
| `prototype/assets/css/design-system.css` | Design-system page furniture only — never used by product screens |
| `prototype/assets/js/app.js` | The whole interaction layer (vanilla, no dependencies) |

## Adding a page

Copy any page's skeleton, then:

- include `partials/head-assets.html` in `<head>` and give the page its own
  `<title>`/description;
- include `partials/icons.html`, `partials/sidebar.html` at the top of `<body>`,
  `partials/topbar.html` inside `.app__body`, and `partials/shell-end.html` +
  `partials/scripts.html` at the end;
- include the sheets the page needs (`sheet-new-case`, `sheet-new-departure`,
  `sheet-add-task`) — they are shared partials, never inline;
- set `<body class="app" data-page="…">`. `app.js` matches `data-page` against
  `data-nav` on the sidebar links to set `is-active` and `aria-current="page"`.
  Existing values: `dashboard`, `approvals`, `notifications`, `directory`,
  `employee`, `cases`, `tasks`, `offboarding`, `departure`, `equipment`,
  `workflows`, `admin-users`, `admin-system`, `reports`, `audit`,
  `design-system`, `handover`.

## Component contracts in `app.js`

These data attributes are the API between markup and behaviour. Reuse them
instead of writing new JavaScript:

- **Role switching** — `[data-role-set="hr|it|facilities|comms|manager|exec|employee|admin"]`
  sets the current role (kept in `sessionStorage`), updates every
  `[data-role-label]`, `[data-role-name]`, `[data-user-name]`, `[data-user-role]`,
  `[data-user-email]`, `[data-user-avatar]`, then shows elements listed in
  `data-roles="a,b"` and hides elements listed in `data-roles-except="a,b"`.
  **Caveat:** never put `data-roles` on `[data-task-row]`, on table rows, or on
  a checklist section — checklist progress and table filtering derive from the
  rendered rows, so hiding rows would falsify the arithmetic. Gate the panels
  around them instead.
- **Droppable menu** — `[data-menu]` + `[data-menu-trigger]` + `[data-menu-panel]`.
- **Filterable table** — `[data-table-region]` wrapping `[data-table-search]`,
  `[data-table-filter="key"]` selects, `<tbody data-table-rows>` whose rows carry
  `data-search` and one `data-<key>` per filter, optional `[data-table-group]`
  segmented buttons with `data-group-value` matching a row's `data-group`,
  optional `[data-table-wrap]`, `[data-table-empty]`, `[data-table-count]` and
  `[data-table-reset]`. `data-count-noun` sets the word used in the count line.
  The segmented tab marked `aria-selected="true"` should be the `all` group,
  because the filter starts unfiltered.
- **Checklist section** — `[data-checklist][data-department="hr|it|facilities|comms"]`
  containing `[data-task-row]`s with a `.task__box` checkbox and a
  `[data-task-status]` badge. Section progress (`[data-section-count]`,
  `[data-section-fill]`, `[data-section-value]`) and the case-level donut
  (`[data-overall-*]`) are recomputed from the rendered rows — the same
  component serves onboarding readiness and departure clearance.
- **Generic confirmation trigger** — any control can drive the shared dialog:
  `data-confirm`, `-title`, `-sub`, `-body`, `-label`, `-tone` (`danger`),
  `-icon`, `-comment="label"`, `-require-comment`, `-status="Approved|ok"`
  (writes a badge into the row's `[data-row-status]` / `[data-decision-target]` /
  `[data-confirm-target]`), `-hide`, `-toast`, `-toast-message`, `-toast-tone`.
  Prefer this over new page-specific JavaScript.
- **Approval decisions** — `data-decision="approve|reject|return"` on a button,
  with `data-request-title` / `data-request-meta` (and optional
  `data-decision-body`). Rejections and returns require a comment; the decision
  writes a badge into `[data-decision-target]` and hides `[data-decision-actions]`.
- **Programmatic dialog** — `window.casidraPrototype.confirm({title, sub, body,
  confirmLabel, icon, tone, askComment, requireComment, commentLabel, onConfirm})`.
  There is exactly one dialog in `partials/shell-end.html`.
- **Sheets (forms)** — `[data-sheet-open="id"]` opens; the form declares
  `data-sheet-form="handler"` and `app.js` dispatches through its
  `SHEET_HANDLERS` registry (`new-case`, `new-departure`, `add-task`). Fields opt
  into validation with `data-validate` (+ `required`, `data-required-message`,
  `data-min-date`). `handleAddTask` clones `<template id="task-template">` from
  `partials/sheet-add-task.html`.
- **Guarded case actions** — `[data-mark-ready]` (onboarding) and
  `[data-mark-clear]` (departure) refuse to proceed while any `[data-task-row]`
  on the page is unticked, and point at `#checklists` / `#clearance` instead.
- **Notification rows** — `[data-notif-item]` with `data-unread="true|false"`,
  a `[data-notif-state]` badge and a `[data-notif-toggle]` button; keep
  `data-group="unread|read"` in step when a `[data-table-group]` filter is used.
- **Prototype toasts** — any element with `data-toast="Title"` plus optional
  `data-toast-message` / `data-toast-tone` shows a toast instead of navigating.
  Used for anything the prototype deliberately does not implement.
- **Status tones** — `badge--ok` (on track / complete), `badge--warn` (at risk /
  awaiting approval / requested), `badge--danger` (overdue / blocked / rejected),
  `badge--info` (in progress), `badge--brand` (administrator / active), neutral
  `badge` (not started). Progress fills mirror these via
  `progress__fill--ok|warn|danger` and `hbar__fill--*`.
- **System-pattern components** — `.role-banner` (role scope notice), `.bars` /
  `.bars__seg--*` (volume chart), `.hbars` / `.hbar__fill--*` (comparison chart),
  `.def-list` / `.def-row` (configuration and settings rows), `.permit--yes|no|limited`
  (permission indicators), `.simulated` ("described but not configured") and
  `.timeline__item--requested` (requested but not yet actioned).

## Non-negotiable rules for this prototype

- **Nothing is saved.** There is no backend call anywhere in `prototype/`.
  Every toast, dialog and empty state must keep saying so. Never describe
  authentication, permissions, approvals, persistence, access removal, email
  delivery, Microsoft 365, Entra ID, MFA, scheduling or exports as implemented —
  they are design only.
- **Mark what is not built.** Any screen describing an integration that does not
  exist carries `.simulated` or an explanatory alert, so a reviewer cannot
  mistake the design for a working feature.
- **Fictional sample data only.** Keep names, dates, numbers and departments
  consistent across pages. The canonical facts:
  - **Onboarding** — Amara Okafor's case is `ONB-2026-0148`: 19 tasks, 9 complete,
    47% ready, starts Tue 3 Nov 2026. The case list shows 12 open cases; the
    dashboard shows 8 of them; the task queue lists 17 tasks (4 overdue, 9 due
    soon, 4 complete).
  - **Departures** — 5 open cases: Helena Marsh `DEP-2026-0031` (Finance, last day
    Fri 30 Oct 2026, 13 clearance actions, 6 complete, 46%), Chiara Rossi
    `DEP-2026-0035` (Facilities, 90%), Raj Patel `DEP-2026-0033` (Technology, 41%),
    Michael Osei `DEP-2026-0036` (Operations, 18%), Yuki Tanaka `DEP-2026-0038`
    (Marketing, 6%). 27 clearance actions outstanding, 9 assets awaiting return.
  - **Approvals** — 9 pending, oldest 5 days; the inbox table lists all 9 (2 waiting
    4+ days, 7 under 4 days).
  - **Assets** — 486 on register, 9 awaiting return, £14,860 outstanding; Helena
    Marsh holds `AST-1042` (laptop), `AST-1043` (phone) and `AST-1180` (dock).
  - **Equipment/directory counts** — 214 employees on record, 12 arriving, 5 leaving.
  If you change one of these numbers, change it everywhere.
- **Accessibility is part of the design**: visible labels, `aria-invalid` and
  `aria-describedby` on invalid fields, `role="alert"` form summaries, status
  text beside every status colour, `aria-current` on active nav and steps, and
  the skip link. Contrast pairs are documented on the design-system page.
- **Reuse before adding.** New patterns belong in `components.css` and as a card
  on `design-system.html` (see the "System patterns" section) so every module
  inherits them.

## Verifying it works

```bash
for p in index cases case tasks directory employee offboarding departure \
         approvals equipment notifications workflows reports audit \
         admin-users admin-system design-system handover; do
  code=$(curl -s -o /tmp/p.html -w '%{http_code}' "http://localhost:3000/$p.html")
  echo "$p $code unresolved=$(grep -c 'unresolved include' /tmp/p.html)"
done
```

Every page must return 200 with `unresolved=0`, and each page carries the one
shared dialog from `partials/shell-end.html` (plus its sheets).

The flows worth exercising in a browser:

- **Dashboard** (`index`) — role switcher changes the navigation, the signed-in
  user and the role-scoped panel; approvals list → `Approve` → dialog →
  confirmation badge; table filter → empty state → reset; global search for
  "helena" or "DEP-2026-0031".
- **Onboarding** — `cases` filters; `case` → tick a checklist box (section and
  case progress recompute) → `Approve` a step → `Request changes` (comment is
  mandatory) → `Add task` → `Mark ready for day one` (blocked while tasks are open).
- **Departures** — `offboarding` filters and `Initiate departure` (validation →
  confirmation); `departure` → tick a clearance box (clearance recomputes from
  46%) → `Record final clearance` (blocked while actions are open) → `Record return`
  on an asset row (status badge changes).
- **Approvals** — `approvals` → `Approve` / `Return` / `Reject`; rejection and
  return refuse to submit without a comment; the history table filters.
- **Administration** — `workflows` activation (comment required);
  `admin-users` role change (comment required); `admin-system` configuration and
  the destructive maintenance action.
- **Role gating** — on `employee`, the restricted panel is visible as HR
  administrator and replaced by an explanatory alert for every other role;
  as IT the Administration group disappears from the navigation.

There is no automated test suite in this repo; the prototype is verified by hand
and with the browser automation tools.

## Quirks

- The root `*.py` scripts are original coursework and contain deliberate
  logic oddities. Leave them and their output alone.
- Pages are flat in `prototype/`, so relative links (`assets/…`, `case.html`)
  work from any page. Keep new pages flat too.
- `partials/icons.html` is an inline SVG sprite; icons are used as
  `<svg class="icon"><use href="#i-name"/></svg>`. Self-closing `<use/>` is
  valid inside SVG content — do not "fix" it.
- Tables marked `.table--stack` restack into labelled rows below **900px**, so on
  a tablet or phone they read as cards. Keep `data-label` on every `<td>`.
- Google Fonts (Inter) is a progressive enhancement; `tokens.css` declares the
  full system fallback stack, so the prototype looks correct offline.
- `data-page` must match a `data-nav` value for the sidebar to highlight the
  current section; a page with no match simply shows no active item.
