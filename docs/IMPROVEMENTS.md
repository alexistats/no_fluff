# Improvements log

A record of the engineering-improvement work carried out against
[`IMPROVEMENT_PLAN.md`](IMPROVEMENT_PLAN.md) (now archived here in `docs/`). All six
phases are complete and merged to `main`.

## Feature work ([`FEATURE_PLAN.md`](../FEATURE_PLAN.md))

- **Phase 1 — Workout management quick wins**: `POST /workout/<id>/delete` (owner-checked,
  cascades to logs, ends the active session if it's the one deleted) with confirm-guarded
  buttons on the dashboard cards and workout detail page; collapsible per-exercise note
  field on both inline log forms (reusing the existing `ExerciseLog.notes` column,
  truncated server-side at 500 chars), surfaced in workout history, the last-session
  summary, and as a 📝 indicator on exercise cards.
- **Phase 2 — Routine visibility (BWF de-emphasis)**: new `User.hidden_routines`
  preference (migration `0003`) with a Settings section to hide/show the built-in
  routines. Hidden routines drop out of the home tabs, schedule pickers, the nav
  fallback, and the default-routine resolution (session view → last workout → first
  visible built-in → first AI program), but stay reachable by direct URL and keep
  their history and labels. The dashboard's "BWF Progressions" section now renders
  only when BWF is visible **and** actually used (a BWF workout or an advancement) —
  registration-seeded progressions alone no longer surface it.
- **Phase 3 — Email foundation + forgot password**: `app/services/email.py` (stdlib
  SMTP with STARTTLS, console-log backend when `MAIL_SERVER` is unset — no new
  dependencies) and `app/services/reset_tokens.py` (itsdangerous timed tokens salted
  with a fragment of the password hash, so they're single-use and die on password
  change; 1-hour expiry). `/forgot_password` (rate-limited 3/hour, uniform response —
  no account enumeration) and `/reset_password/<token>`; emailed links are built from
  `APP_BASE_URL` when configured to keep Host-header spoofing out of reset emails.
  Post-ship: a Brevo HTTPS-API backend was added (`BREVO_API_KEY`, takes precedence)
  after discovering Render blocks outbound SMTP ports.
- **Phase 4 — Calendar feed + reminder emails**: per-user tokenized iCalendar feed
  (`/calendar/feed/<token>.ics`, hand-assembled RFC 5545 in `app/services/ics.py` —
  all-day events, escaping, 75-octet folding) with enable/copy/regenerate/disable
  controls on the Schedule page; works with Google Calendar, Cozi, and Apple Calendar.
  Reminder emails: per-user local send time (browser-captured UTC offset), stamped
  idempotent via `last_reminded_on`, triggered by an hourly GitHub Actions cron
  (`.github/workflows/reminders.yml`) hitting `POST /tasks/send_reminders` guarded by
  `CRON_SECRET` + `compare_digest`. Migration `0004` adds the five user columns.

**Quality bar throughout:** every phase shipped CI-green (ruff + pytest), the
suite grew to **70 tests at ~88% coverage**, and the frontend/PWA phases were
verified end-to-end in a headless browser (Playwright).

| Phase | Theme | Merged in |
|---|---|---|
| 1 | Safety net (CI, linting, secrets, logging) | PR #14 |
| 2 | Database integrity (migrations, indexes, cascades) | PR #14 |
| 3 | Robustness (rate limiting, crash fixes, AI hardening) | PR #15 |
| 4 | Test coverage + service layer | PR #15 |
| 5 | Frontend quality | PR #15 |
| 6 | PWA (installable, offline-tolerant) | PR #16 |

## Phase 1 — Safety net

- **CI**: GitHub Actions workflow running `ruff check`, `ruff format --check`, and
  `pytest` on every push/PR; ruff + pytest config in `pyproject.toml`.
- **`SECRET_KEY` hard-fail**: the app refuses to boot on the insecure dev key when
  a production signal is present (`RENDER`, or a non-SQLite `DATABASE_URL`).
- **Fernet resilience**: an undecryptable stored user API key no longer 500s the
  Settings page — it prompts the user to re-enter it, and generation falls back to
  the server key. Optional `FERNET_KEY` decouples the cipher from `SECRET_KEY`.
- **Logging** via `app.logger` (`LOG_LEVEL`), and a fix for account-enumeration on
  the register form.

## Phase 2 — Database integrity

- **Flask-Migrate** replaces `db.create_all()`. On startup the app upgrades to head;
  a database predating migrations is **stamped at a baseline** and then upgraded, so
  the existing Neon database is adopted without recreating tables (`AUTO_MIGRATE`
  gates this; tests build their schema in the fixture).
- **Indexes** on the hot foreign keys (`Workout.user_id`, `ExerciseLog.workout_id`,
  and `user_id` on `UserProgression`/`CustomExercise`/`HiddenExercise`/`RotationEntry`).
- **Delete cascades** (`all, delete-orphan`) so removing a user no longer orphans
  rows across its child tables.

## Phase 3 — Robustness

- **Rate limiting** (Flask-Limiter): 5/min on login + register POST; 3/hour on AI
  generation **when using the shared server key** (own-key users exempt).
- **Crash fixes**: tolerant reps parsing (`"30s"` no longer crashes reads),
  `request.get_json(silent=True)` on JSON endpoints (malformed body → 400, not 500),
  and UTC-consistent dashboard date math.
- **AI generation**: surfaces `stop_reason` (truncation / refusal) with clear
  messages and retries invalid output with a correction turn instead of an identical
  request. Dead code removed (the `/progress` redirect, always-`None` args, an empty
  conditional).

## Phase 4 — Test coverage + service layer

- Tests **first** as a refactor harness for the previously-untested dashboard,
  schedule, rotation, plan/unplan, logout, exercise-detail, and CSRF surface.
- Extracted `app/services/routines.py` and `app/services/stats.py`: the dashboard
  aggregation became bounded SQL (`COUNT`/`GROUP BY`) instead of loading every
  workout into Python, and the weight-trend N+1 became a single grouped query — with
  byte-identical output (pinned by the harness). CI coverage floor enabled.

## Phase 5 — Frontend quality

- **Cache-busting** `static_url()` helper (content-hash `?v=`) on all assets.
- **Vendored Chart.js** locally (dropped the un-SRI'd CDN); extracted the dashboard
  and schedule inline JS to `static/js/dashboard.js` / `schedule.js` with server data
  via `<script type="application/json">` blocks; replaced the private `Chart.instances`
  usage with a chart registry.
- Shared `fetchJSON()` with **error toasts**, a guarded CSRF-meta lookup, a
  "Logging…" pending state, single-sourced equipment icons, and **accessibility**
  (ARIA accordion state, labeled icon buttons, canvas text fallbacks).

## Phase 6 — Progressive Web App

- **Installable**: `manifest.json` + 192/512/maskable icons and the web-app meta tags.
- **Service worker** (`/sw.js`, root scope): cache-first static assets, network-first
  navigations with a cached `/offline` fallback, never intercepts non-GET requests.
- **Log-form drafts**: in-progress forms persist to `localStorage` and restore on
  load (cleared on a successful log), so a dropped connection doesn't lose a set.

## Deliberately deferred

Tracked for later; called out so they aren't forgotten:

- **AI generation streaming** — the plan suggested switching to
  `client.messages.stream()`. Deferred because it couldn't be verified against the
  live API in the working environment, and the existing 120s/300s timeouts already
  cover the long-request case. The `stop_reason` and retry improvements landed behind
  a `_get_completion` seam that makes a later streaming swap low-risk.
- **Two template macros** — unifying the two `home.html` log forms, and merging the
  `home` / `preview_program` exercise-card headers. Skipped because those headers
  diverge (one is an interactive accordion coupled to `main.js`'s DOM contract, the
  other is static), so a shared macro would add coupling risk for little gain.

## Operational notes

- Set **`SECRET_KEY`** in production (now a hard requirement). To rotate it later
  without losing stored user API keys, set **`FERNET_KEY`** to the currently derived
  value first (see the README).
- The **first production boot** after Phase 2 auto-runs the index migration
  (low-risk); set `AUTO_MIGRATE=0` and run `flask db upgrade` manually to apply it
  deliberately.
- **Rate limits** are live (login 5/min; shared-key AI generation 3/hour) and tunable
  via the `@limiter.limit(...)` decorators in `app/routes.py`.
- Bump `VERSION` in `static/js/sw.js` when cached assets should be force-refreshed on
  clients.
