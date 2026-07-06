# NoFluff Feature Plan (July 2026)

A phased plan implementing the owner's feature requests, written to be executed by
future coding sessions (Claude Opus 4.8 on max effort), **one phase per session**.
It follows the same conventions as the engineering improvement plan
([`docs/IMPROVEMENT_PLAN.md`](docs/IMPROVEMENT_PLAN.md), completed and archived — see
[`docs/IMPROVEMENTS.md`](docs/IMPROVEMENTS.md)).

## The requests → phases

| # | Request (owner's words, paraphrased) | Phase |
|---|---|---|
| 1 | "Can we connect to Google Calendar or the app Melissa has?" | 4 |
| 2 | "Too much emphasis on BWF routine — if I'm not using it, it should not be on the dashboard etc." | 2 |
| 3 | "Add a way to delete workouts" | 1 |
| 4 | "Optional comment section for exercises during a workout" | 1 |
| 5 | "We need forgot-password handling" | 3 |
| 6 | "Email reminders for workouts — any free option?" | 4 |
| 7 | "Make the offline experience actually useful — cache home/last routine, log offline, sync on reconnect" | 5 |
| 8 | "Lock the shared API key under a password I can share (premium later)" | 6 |

## How to use this document

- Execute phases **in order** by default. Dependency edges: Phase 4 requires Phase 3
  (email service). Phases 1, 2, 5, 6 are independent of everything else and can be
  cherry-picked or reordered if the owner asks.
- Each phase is independently shippable: it ends with green CI (`ruff check .`,
  `ruff format --check .`, `pytest`), a reviewed migration if schema changed, updated
  docs, and the Status checklist at the bottom of this file ticked.
- One phase = one branch = one PR to `main`, titled `Phase N: <phase name>`.
- File references are repo-relative with line numbers as of commit `79a937b` — re-locate
  by symbol/content if lines have drifted.
- **No new runtime dependencies are needed for any phase.** Email uses stdlib
  `smtplib`/`email.message`, reset tokens use `itsdangerous` (already installed via
  Flask), the ICS feed is hand-assembled text, offline sync is vanilla JS + IndexedDB.
  This is deliberate (see D4) — do not add packages without recording why here.
- When a phase changes anything the service worker caches (`static/js/*.js`,
  `static/css/style.css`, templates that get precached), bump `VERSION` in
  `app/static/js/sw.js`.
- Some steps need the **owner**, not the coding session (signing up for an SMTP
  provider, setting env vars on Render, adding a GitHub Actions secret). These are
  collected in **Human setup tasks** below; each phase's PR description must list the
  ones it introduces under an "Owner TODO" heading. Code must degrade gracefully when
  the owner hasn't done them yet (e.g. email unconfigured → console backend).

## Current-state notes (read before starting)

- **Exercise comments are already half-built.** `ExerciseLog.notes` exists
  (`app/models.py:89`), both log handlers already read `request.form.get('notes', '')`
  (`app/routes.py:592` and `:613`), and `workout_detail.html:48-51` already renders
  notes. Phase 1 only adds the missing input UI.
- **BWF is the hardcoded fallback everywhere**: `_default_routine_view()` returns
  `'bwf'` (`app/routes.py:127-139`), the nav "Start Workout" link falls back to `'bwf'`
  (`app/templates/base.html:61`), home tabs render BWF first unconditionally
  (`home.html:9-14`), and the dashboard "BWF Progressions" section
  (`dashboard.html:83-104`) always renders because registration seeds a
  `UserProgression` row for every category (`app/routes.py:315-325`).
- **Auth is username/password only** (`app/routes.py:270-330`), rate-limited 5/min.
  `User.email` is unique+indexed. There is no email-sending code anywhere.
- **Scheduling already exists**: `WorkoutSchedule` (date + routine per user, unique per
  date) and `RotationEntry` (`app/models.py:216-237`), managed on `/schedule`. Phase 4
  builds reminders/calendar on top of these — no new scheduling concepts.
- **Service worker** (`app/static/js/sw.js`, 55 lines): static assets cache-first,
  navigations network-first falling back to a precached `/offline` page. Nothing
  authenticated is cached today (README makes that claim — Phase 5 changes it, update
  the README section). Log-form drafts already persist to `localStorage`
  (`app/static/js/main.js:45-70`); AJAX logging posts with `X-Requested-With`
  (`main.js:208-212`) and the server branches on it (`app/routes.py:66-67`, `:545`).
- **Shared AI key**: `resolve_api_key` (`app/ai_generator.py:105-114`) falls back to
  the server-wide `ANTHROPIC_API_KEY` for every logged-in user; the only guard is a
  3/hour rate limit (`app/routes.py:857-859`).
- **Prod**: Render free tier (sleeps after ~15 min idle; a request wakes it in
  30–60 s) + Neon Postgres. Single gunicorn worker; in-memory rate limiter. Startup
  auto-migration is in place (`app/__init__.py:78-103`).
- Tests: `tests/conftest.py` provides `app` / `client` / `logged_in_client` fixtures;
  CSRF and rate limits are disabled in `TestConfig`. ~70 tests, coverage floor in CI.

## Recorded design decisions

Recorded up front so executing sessions don't relitigate them. If one proves wrong in
practice, stop and say so in the PR rather than silently doing something else.

### D1 — Routine de-emphasis is a per-user visibility preference, not removal

Add `User.hidden_routines` (string, comma-separated keys from `{'bwf','gym'}`, default
`''`). Hiding a routine removes it from the home tabs, default-routine fallback,
schedule pickers, and dashboard — it does **not** delete history, progressions, or
block direct URLs (`/?routine=bwf` still works; `_valid_routine_key` is unchanged).
Registration keeps seeding BWF progressions (harmless, needed if the user opts back
in). The dashboard's BWF Progressions section renders only when BWF is visible **and**
the user has BWF activity (any `bwf` workout or any progression above level 1) — so
even users who keep BWF visible but never use it get a clean dashboard. A user cannot
hide every routine: reject hiding the last visible one unless they have at least one
accepted AI program.

### D2 — Exercise comments reuse `ExerciseLog.notes`

No schema change. Add a collapsed "＋ Add note" toggle revealing a
`<textarea name="notes" maxlength="500">` on each log form; server-side truncate to
500 chars in both `_log_gym_exercise` and `_log_bwf_exercise`. Notes ride the existing
form serialization (AJAX `FormData` and the localStorage draft mechanism pick up any
named field — verify the draft code covers textareas, fix if not).

### D3 — Workout deletion is a POST with confirm; progressions are not rolled back

`POST /workout/<id>/delete`, `login_required`, owner-checked, ORM cascade already
deletes the logs (`Workout.exercises` has `all, delete-orphan`). If the deleted
workout is the session's active one, also pop `current_workout_id` /
`current_routine_type`. Delete buttons live on `workout_detail.html` and on each
Recent Workouts card in `dashboard.html`, both behind a JS `confirm()`. Deleting a BWF
workout that triggered a progression advance does **not** demote the progression —
document this in the PR; it's accepted behavior (progressions are a high-water mark).

### D4 — Email is plain SMTP via stdlib, behind a tiny service module

New `app/services/email.py` exposing `send_email(to, subject, text, html=None) -> bool`.
Backend chosen by config: if `MAIL_SERVER` is set → SMTP (STARTTLS, port 587 default,
`MAIL_USERNAME`/`MAIL_PASSWORD`/`MAIL_FROM`); otherwise → console backend that logs the
message (including any links) at INFO. No provider SDK, no Flask-Mail — SMTP works
with every free provider (recommended: **Brevo**, free 300 emails/day, no custom
domain required; Gmail app-password SMTP also works at this scale). Send failures are
logged and return `False`; callers must not leak success/failure to the browser where
that would enable account enumeration. Tests monkeypatch `send_email`.

### D5 — Password reset uses itsdangerous timed tokens; no enumeration

No new table. Token = `URLSafeTimedSerializer(SECRET_KEY, salt='password-reset')`
signing `{user_id, fragment-of-password-hash}`; verifying checks `max_age=3600` and
that the hash fragment still matches (so a token dies once the password changes —
single-use without storage). Routes: `GET/POST /forgot_password` (email form; always
the same flash "If that email is registered, a reset link is on its way", rate-limit
`3/hour` per IP) and `GET/POST /reset_password/<token>` (new password twice, reuse
`MIN_PASSWORD_LENGTH`, then redirect to login). Add the "Forgot password?" link to
`login.html`. Absolute links in email come from `APP_BASE_URL` config when set,
falling back to `request.url_root` — never trust the Host header alone in production
(host-header injection in reset emails). Add `APP_BASE_URL` to the README env table
and Render owner TODO.

### D6 — Calendar integration = per-user secret ICS feed; Google Calendar OAuth is deferred

Full Google Calendar API integration (OAuth consent screen, token storage, verification)
is out of proportion for a two-user app — **deferred indefinitely** unless the owner
asks again. Instead: `GET /calendar/feed/<token>.ics` serving the user's
`WorkoutSchedule` entries for the next 8 weeks as all-day VEVENTs (plus a `VALARM` at
a fixed morning hour). `token` = `secrets.token_urlsafe(24)` stored in a new nullable
unique `User.ics_token` column; the `/schedule` page gains "Enable calendar feed" /
"Copy link" / "Regenerate link" controls (regenerate revokes the old URL). The route is
unauthenticated by design (calendar apps fetch anonymously); unknown token → 404; feed
contains only dates and routine labels. Hand-assemble the ICS (CRLF line endings,
escaped text, stable `UID`s like `nofluff-sched-<id>@nofluff`) — no dependency.
**Honest caveats to put in the UI hint and PR:** Google Calendar refreshes subscribed
URLs only every ~12–24 h and ignores `VALARM` on subscribed feeds, so the feed is for
*seeing* workouts in a calendar app; *reliable reminders* are the email path. Apple
Calendar honors alarms and refresh intervals better. **Cozi** (the family's shared
calendar) subscribes to ICS URLs natively — *Settings → Connected Calendars → Add a
calendar from a URL* — and refreshes roughly hourly, so this one feed covers both
Google Calendar and Cozi with no extra work. One wrinkle for both fetchers: the Render
free dyno sleeps, and a cold start (30–60 s) can make a fetch attempt time out; that's
tolerable (the fetcher retries on its next cycle) and the hourly reminder cron (D7)
doubles as a keep-warm ping.

### D7 — Email reminders: daily, opt-in, driven by an external free cron hitting a token-guarded endpoint

Render free tier has no built-in scheduler and the dyno sleeps, so scheduling lives
outside: a GitHub Actions scheduled workflow (`.github/workflows/reminders.yml`, cron
`0 * * * *`) curls `POST $APP_URL/tasks/send_reminders` with
`Authorization: Bearer $CRON_SECRET` (repo secret). Free on public repos; if the repo
is private and minutes are a concern, cron-job.org is the fallback — the endpoint
doesn't care who calls it. The endpoint (CSRF-exempt, compares the bearer token with
`hmac.compare_digest` against `CRON_SECRET` config, 403 otherwise, disabled when the
env is unset) selects users with `reminder_enabled` whose **local** time has passed
their chosen reminder time and who have a `WorkoutSchedule` entry for their local
today, sends "You have <routine label> planned today" (link via `APP_BASE_URL`), and
stamps `last_reminded_on` (local date) for idempotency across hourly runs. New `User`
columns: `reminder_enabled` (bool, default false), `reminder_time` (string `'HH:MM'`,
default `'07:00'`), `tz_offset_minutes` (int, captured from the browser by JS when the
settings form is saved), `last_reminded_on` (date, nullable). DST being an hour off
twice a year is accepted. Settings UI lives in a new "Reminders" section on
`settings.html`. Rotation suggestions do **not** trigger emails — only explicitly
scheduled workouts (no spam; nudges people to use the calendar). The endpoint returns
`{"sent": n, "skipped": m}` for observability, and doubles as a keep-warm ping.

### D8 — Offline: cached pages + an IndexedDB outbox synced to one idempotent batch endpoint

Service worker v2 (`VERSION = 'v2'`):
- **Runtime page cache**: successful same-origin GET navigation responses are cached
  (network-first; on network failure serve the cached copy, else `/offline`). Exclude
  `/login`, `/register`, `/settings`, `/logout`, `/calendar/*`, `/sw.js`. This makes
  the home page (with inline log forms) and the last-viewed routine available offline.
  Cached pages are personal content on the device: clear the runtime cache on logout
  (logout click handler in `main.js` awaits `caches.delete(...)`) and update the
  README's "Nothing authenticated is cached" claim.
- **Offline banner**: `main.js` shows a dismissible "Offline — sets you log will sync
  when you're back" banner on `offline` events / `!navigator.onLine`.

**Outbox** (vanilla IndexedDB in `main.js` or a new `static/js/offline.js`): when the
existing AJAX log submit fails on a network error (not an HTTP error), store
`{client_log_id: uuid, client_workout_id, workout_id?, routine_type, section,
exercise_name, fields, created_at}` and show the success UI in a "saved offline —
pending sync" variant. Two flows share it:
1. *Connection drops mid-workout* (the common gym case): the page embeds the active
   server `workout_id` (template exposes `session['current_workout_id']` as a data
   attribute), queued logs carry it.
2. *Fully offline start*: if "Start Workout" is tapped while offline, JS creates a
   local active workout `{client_uuid, routine_type, started_at}` in `localStorage`
   and the inline forms log against it; "End workout" offline just marks it done
   locally.

**Sync**: on `online`, on page load, and via Background Sync where supported, POST the
outbox grouped per workout to a new `POST /sync/workout` endpoint — JSON body
`{client_uuid?, workout_id?, routine_type, started_at?, logs: [{client_log_id,
exercise_name, section, reps: [...], weights: [...], weight_unit, progression_level,
notes, logged_at}]}`. Server behavior: `login_required` (401 keeps the outbox and
shows a "log in to sync" banner); CSRF-exempt but **requires** the
`X-Requested-With: XMLHttpRequest` header and a JSON content-type (both force a CORS
preflight cross-origin, which is the CSRF defense); find-or-create the workout by
`(user_id, client_uuid)` or verify ownership of `workout_id`; insert logs skipping any
`client_log_id` already present; run `maybe_advance_progression` for BWF logs in
order; return accepted ids so the client can clear only acknowledged entries.
Idempotency columns (one migration): `Workout.client_uuid` (nullable, unique with
`user_id`) and `ExerciseLog.client_log_id` (nullable, unique). Duplicate-proof against
lost responses and double `online` events.

Out of scope for the phase: offline dashboard/charts, offline routine editing,
conflict resolution beyond "server already has this client_log_id".

### D9 — Shared-key lock: an access code in an env var unlocks a per-user flag

New env/config `SHARED_KEY_ACCESS_CODE`. When unset → today's behavior (backward
compatible). When set: `resolve_api_key` returns the server key only for users with
the new `User.shared_key_unlocked_at` timestamp set. Unlock form in a new
"Shared AI access" section of `settings.html` (shown when a server key exists and a
code is configured): POST the code, compare with `hmac.compare_digest`, rate-limit
`5/minute`, set the timestamp on success. `generate.html`'s no-key message and
`settings.html` copy explain: "ask the owner for the access code, or add your own API
key." Changing the code does *not* re-lock existing users (the flag persists) — if the
owner wants a re-lock lever later, that's a follow-up (`shared_key_unlocked_at` being
a timestamp, not a bool, is deliberate: a future "code rotated at T, re-lock anyone
unlocked before T" needs no migration). This is the stepping stone to a future
premium flag; keep the gate in one function so swapping "entered the code" for "has an
entitlement" is a one-line change.

---

## Phase 1 — Workout management quick wins (delete + per-exercise notes)

Requests #3 and #4. No migration. Smallest phase; good warm-up.

**Tasks**
1. `POST /workout/<int:workout_id>/delete` in `app/routes.py` near `view_workout`
   (`:799`), per D3. Flash "Workout deleted." and redirect to the dashboard.
2. Delete buttons: `workout_detail.html` (top, next to the date) and each card in the
   Recent Workouts list (`dashboard.html:110-118`) — small forms with `csrf_token`,
   `onsubmit="return confirm('Delete this workout and its logs?')"`. Match existing
   button classes (`restore-btn` is the destructive-secondary pattern, see
   `home.html:33-36`).
3. Notes UI per D2: in the gym and BWF inline forms in `home.html` (BWF form around
   `:225`, gym form nearby — locate by `name="notes"` *absence* and the set-input
   macros) **and** the forms in `exercise.html`. A `<button type="button">` toggle
   ("＋ Add note") revealing the textarea keeps the mobile forms compact. Style in
   `style.css` consistent with existing form styles.
4. Server-side truncation `[:500]` at `app/routes.py:592` and `:613`.
5. Show a 📝 indicator with a `title` tooltip in the last-session preview on
   `home.html` when the previous log has a note (data is already in `last_logs`).
6. Verify the draft persistence (`main.js:45-70`) captures textareas; fix if it
   iterates only `input` elements.

**Tests** (`tests/test_workout_management.py`): delete own workout removes its
`ExerciseLog` rows; deleting another user's → redirect + still exists; deleting the
active workout clears the session key (log again → "No active workout"); notes
round-trip for both gym and BWF logging (and >500 chars truncated); notes appear on
the workout detail page.

**Verification**: full CI trio; manual (or Playwright) phone-width pass: log a set
with a note in both routine styles, see it on the detail page, delete the workout.
Bump sw `VERSION` (main.js/style.css changed).

## Phase 2 — De-emphasize BWF (routine visibility preferences)

Request #2. Migration: add `User.hidden_routines` (per D1).

**Tasks**
1. Model: `hidden_routines` column + helpers `User.is_routine_hidden(key)` /
   `User.visible_builtin_routines()` (`app/models.py:35-65`). Generate + review the
   migration.
2. Settings: new "Routines" section on `settings.html` with checkboxes for BWF/Gym
   visibility; handle via the existing settings POST with an `action='routines'`
   discriminator (`app/routes.py:985-1007`). Enforce the can't-hide-everything rule
   from D1 with a flash.
3. Thread visibility through:
   - Home tabs `home.html:9-24`: skip hidden built-ins (pass a `visible_builtins`
     list from the route rather than testing `current_user` in the template).
   - `_default_routine_view` (`app/routes.py:127-139`): fallback order becomes
     session view (if valid **and** not hidden) → last workout's routine (same
     condition) → first visible built-in → first accepted AI program.
   - `base.html:61` Start Workout fallback: same helper, not the `'bwf'` literal.
   - Schedule pickers `app/routes.py:725-728`: only visible built-ins (existing
     scheduled/rotation entries for hidden routines keep working — `_valid_routine_key`
     unchanged).
   - `start_workout` fallback `app/routes.py:489-491`.
4. Dashboard: compute `show_bwf_progressions` in the route per D1 (BWF visible AND
   (a `bwf` workout exists OR any `UserProgression.current_progression > 1`)); wrap
   `dashboard.html:83-104` with it.

**Tests** (`tests/test_routine_visibility.py`): hiding BWF removes it from home tabs
and schedule payload; default view for a fresh user with BWF hidden is gym; dashboard
hides/shows the progressions section per the rule; hiding both built-ins with no AI
program is rejected; direct `/?routine=bwf` still renders when hidden.

**Verification**: CI trio; migration applies on a copy of a dev SQLite db; manual pass
of home/dashboard/schedule with BWF hidden. Update README's feature list (BWF framing
in the intro) to mention routines are hideable.

## Phase 3 — Email foundation + forgot password

Request #5. No migration. Prerequisite for Phase 4.

**Tasks**
1. `app/services/email.py` per D4; config additions in `config.py`: `MAIL_SERVER`,
   `MAIL_PORT` (587), `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `APP_BASE_URL`
   (all optional, README env table updated).
2. Reset-token helpers per D5 (put them in `app/services/` or next to the auth routes;
   they need `SECRET_KEY` and the user's `password_hash`).
3. Routes `forgot_password` / `reset_password` per D5, templates
   `forgot_password.html` / `reset_password.html` matching `login.html`'s
   `auth-container` style, "Forgot password?" link on `login.html:16-18`.
4. On successful reset: `flash('Password updated — log in with your new password.')`;
   do **not** auto-login.
5. Email copy: plain text is fine ("Reset your NoFluff password: <link> — expires in
   1 hour. Ignore this if it wasn't you.").

**Tests** (`tests/test_password_reset.py`): request-reset for unknown email returns
the same flash and sends nothing (monkeypatched `send_email` capture); valid flow
end-to-end (capture the link, GET the form, POST a new password, old password fails /
new works); expired token (freeze/patch `max_age`) rejected; token invalid after the
password changes; short new password rejected; rate limit on the request form
(pattern in `tests/test_ratelimit.py`).

**Verification**: CI trio. Manual: with no `MAIL_SERVER`, the reset link appears in
the app log and works. **Owner TODO in PR**: create a Brevo (or similar) SMTP
credential and set `MAIL_*` + `APP_BASE_URL` on Render.

## Phase 4 — Workout reminders: ICS calendar feed + reminder emails

Requests #1 and #6. Depends on Phase 3. Migration: `User.ics_token` + the four
reminder columns (D6/D7).

**Tasks**
1. ICS feed per D6: `app/services/ics.py` (pure function: user + schedules → ICS
   string, easily unit-tested), route `GET /calendar/feed/<token>.ics`
   (`Content-Type: text/calendar`), token lifecycle actions on `/schedule`
   (enable/copy/regenerate; copy button JS in `schedule.js`), UI hint text with the
   D6 caveats.
2. Reminder settings per D7: "Reminders" section on `settings.html` (enable checkbox +
   time input + hidden `tz_offset_minutes` filled by JS `new Date().getTimezoneOffset()`
   — note the sign flip: JS gives minutes *behind* UTC).
3. `POST /tasks/send_reminders` per D7 (in a small new blueprint or under a
   `# ── Tasks ──` section of routes; CSRF-exempt via `csrf.exempt`).
4. `.github/workflows/reminders.yml`: hourly cron + `workflow_dispatch` for manual
   runs; single `curl -fsS` step using `secrets.CRON_SECRET` and `vars.APP_URL`.
5. Email copy: subject "Workout today: <routine label>", body with the routine name
   and a link to `<APP_BASE_URL>/`.

**Tests** (`tests/test_reminders.py`, `tests/test_ics.py`): ICS output has valid
skeleton (BEGIN/END, CRLF, UID stability, escaping of a routine named e.g.
`Legs; heavy, maybe`), only the owner's next-8-weeks entries; unknown/regenerated
token → 404; reminders endpoint: 403 without/with-wrong bearer; disabled when
`CRON_SECRET` unset; sends only when local-time threshold passed **and** workout
scheduled today **and** not already stamped (drive times via injected "now" or
`tz_offset_minutes` fixtures); idempotent across two calls; response counts correct.

**Verification**: CI trio; subscribe the feed URL from a phone calendar app if
possible, else validate the .ics with a validator. **Owner TODO in PR**: set
`CRON_SECRET` on Render + repo secret `CRON_SECRET` + repo variable `APP_URL`; answer
the Melissa question (below) — if her app subscribes to calendar URLs, share the feed
link; done.

## Phase 5 — Offline that's actually useful

Request #7. The biggest phase — implement D8 exactly; if anything must be cut, cut
the *fully offline start* flow (5.2 flow 2), never the mid-workout drop flow.
Migration: `Workout.client_uuid`, `ExerciseLog.client_log_id`.

**Tasks**
1. Service worker v2 (runtime navigation cache + exclusions + logout clearing + README
   update) per D8.
2. Outbox + the two logging flows per D8 (new `app/static/js/offline.js`, loaded from
   `base.html` with `static_url()`; keep `main.js`'s submit handler as the integration
   point — on network failure call `outbox.enqueue(...)`).
3. `POST /sync/workout` per D8, plus the migration.
4. Pending-sync UI: per-exercise "saved offline" state, a global "N sets waiting to
   sync" pill that triggers sync on tap, and the offline banner.
5. Background Sync registration where available (progressive enhancement; the
   `online`-event path is the baseline that must work everywhere, including iOS).

**Tests** (`tests/test_sync.py`): batch creates workout+logs for a fresh
`client_uuid`; replay of the same batch creates nothing new and returns the same ids;
partial replay (one new + one known `client_log_id`) inserts only the new one; logs
attach to an existing owned `workout_id`; someone else's `workout_id` → 403/404;
unauthenticated → 401; missing `X-Requested-With` → 400/403; BWF logs advance
progressions through the sync path (reuse expectations from `tests/test_progression.py`).

**Verification**: CI trio; **required E2E**: Playwright (Chromium is pre-installed in
the session environment) — log in, load home, `context.setOffline(true)`, navigate
home from cache, log two sets, `setOffline(false)`, assert the logs land in the DB.
Bump sw `VERSION`. Update README PWA section honestly (what's cached, what syncs,
logout clears cache).

## Phase 6 — Lock the shared API key behind an access code

Request #8. Migration: `User.shared_key_unlocked_at`. Implement D9 exactly.

**Tasks**
1. Config `SHARED_KEY_ACCESS_CODE` + README env row.
2. Migration + model column.
3. Gate inside `resolve_api_key` (`app/ai_generator.py:105-114`) — keep the
   user-key-first order; only the server-key fallback becomes conditional. It needs
   the user and the config; keep the signature `resolve_api_key(user)`.
4. Unlock form in `settings.html` + handler (`action='unlock_ai'`) per D9, rate
   limited `5/minute`.
5. Copy updates: `settings.html` shared-key paragraph (`:9-17`) and the
   no-key flash in `generate` (`app/routes.py:872-873`, `:945-947`).

**Tests** (`tests/test_shared_key_lock.py`): with code configured, a locked user's
`resolve_api_key` returns None (server key set, no user key) and `/generate` POST
redirects to settings; wrong code → still locked + flash; right code → unlocked,
server key resolves; code unset → today's behavior (regression guard on existing
tests); user's own key bypasses the lock entirely.

**Verification**: CI trio. **Owner TODO in PR**: choose the code, set
`SHARED_KEY_ACCESS_CODE` on Render, share it with Melissa.

---

## Human setup tasks (owner checklist — code never blocks on these)

- [ ] **Phase 3**: sign up for an SMTP provider (recommended: Brevo free tier, 300/day)
      → set `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`
      on Render. Also set `APP_BASE_URL` (e.g. `https://<app>.onrender.com`).
- [ ] **Phase 4**: set `CRON_SECRET` on Render; add repo **secret** `CRON_SECRET`
      (same value) and repo **variable** `APP_URL`; enable the workflow.
- [ ] **Phase 4**: subscribe to the feed — Google Calendar: *Other calendars → From
      URL*; Cozi: *Settings → Connected Calendars → Add a calendar from a URL*
      (share the same feed link with Melissa's Cozi).
- [ ] **Phase 6**: set `SHARED_KEY_ACCESS_CODE` on Render; share the code.

## Open questions (non-blocking — defaults are chosen)

1. ~~"The app Melissa has"~~ — **answered: Cozi.** Cozi subscribes to internet
   calendars by ICS URL and refreshes about hourly, so the Phase 4 feed covers it
   directly (see D6). Nothing extra to build, nothing to drop.
2. **Email provider** — plan assumes Brevo; any SMTP credential works without code
   changes.
3. **Repo visibility** — if `alexistats/no_fluff` is private, GitHub Actions cron
   spends free minutes (~750/month at hourly runs, within the 2000 free tier but
   noticeable); cron-job.org is the zero-cost alternative and needs no code change.

## Status

Tick when the phase's PR is **merged**. The executing session updates this file and
appends a short entry to `docs/IMPROVEMENTS.md` (new "Feature work" section) in the
same PR as the phase itself.

- [x] Phase 1 — Workout management quick wins (delete + notes)
- [x] Phase 2 — De-emphasize BWF (routine visibility)
- [ ] Phase 3 — Email foundation + forgot password
- [ ] Phase 4 — Reminders: ICS feed + email
- [ ] Phase 5 — Offline logging + sync
- [ ] Phase 6 — Shared-key access lock

## Kickoff prompt (reuse for every session)

> Read `FEATURE_PLAN.md` in full before writing any code. Find the first unchecked
> phase in its Status section and execute exactly that phase — nothing from later
> phases, no scope additions. The design decisions (D1–D9) are settled; implement
> them as written, and if one turns out to be genuinely unworkable, stop and explain
> in the PR instead of substituting your own design. Follow the repo's existing
> conventions (route/template/test patterns, ruff config); re-locate cited line
> numbers by symbol if they've drifted. If the phase changes the schema, generate the
> Flask-Migrate migration and review it by hand. Add the phase's tests, then verify:
> `ruff check .`, `ruff format --check .`, and `pytest` must all pass, plus the
> phase's own Verification steps (including Playwright for Phase 5). Bump the service
> worker VERSION if you changed any cached static asset. Update the README where the
> phase says so, tick the phase in FEATURE_PLAN.md's Status section, and append a
> short entry to `docs/IMPROVEMENTS.md` under a "Feature work" section. Commit in
> logical chunks with clear messages, push, and open a PR to `main` titled
> "Phase N: <phase name>" whose description summarizes what changed, lists any
> "Owner TODO" env/setup steps the phase introduces, and notes anything you
> deliberately deviated from in the plan.
