# NoFluff Improvement Plan

A phased roadmap to improve NoFluff's engineering health, test coverage, code quality, and
user experience. Written to be executed by future coding sessions (e.g. Claude Opus 4.8),
one phase per session.

## How to use this document

- Execute phases **in order**. Each phase is independently shippable and ends with explicit
  verification steps; do not start a phase until the previous phase's verification passes.
- Within a phase, tasks are ordered by dependency.
- Run `pytest` before and after every phase. From Phase 1 onward, CI must be green.
- File references are repo-relative with approximate line numbers as of the commit that
  introduced this document — re-locate by symbol/content if lines have drifted.
- Dependency additions across the plan: `Flask-Migrate`, `Flask-Limiter` (runtime);
  `ruff`, `pytest-cov` (dev).

## Current-state assessment (July 2026)

Solid small Flask 3 app: app factory, single blueprint (`app/routes.py`, ~1070 lines),
10 models, an Anthropic-powered program generator with correct modern API usage
(structured output + adaptive thinking), ~37 meaningful pytest tests, and thoughtful
production config (connection pooling, Python pinning, factory-aware Procfile for
Render + Neon Postgres). The main gaps:

1. **No schema migration mechanism.** `db.create_all()` (app/__init__.py:38-39) only creates
   missing tables — it never alters existing ones, so column additions silently never reach
   the deployed Postgres database.
2. **Secrets fragility.** `SECRET_KEY` falls back to an insecure literal with only a warning
   (config.py:5-9), and the Fernet key encrypting user API keys is derived from `SECRET_KEY`
   (app/models.py:95-98) — rotating it permanently bricks stored keys and 500s the Settings
   page (`key_hint()` → `get_key()`).
3. **No CI, no linting, no logging, no rate limiting.**
4. **Newest features untested**: `/dashboard`, `/schedule`, rotation/plan endpoints.
5. **Frontend debt**: heavy inline JS, duplicated template blocks, accessibility gaps,
   inconsistent error/loading states, no PWA support despite being a mobile-first gym app.

## Recorded design decisions

Recorded up front so future sessions don't relitigate them.

### Decision 1 — Migrations: Flask-Migrate with baseline-and-stamp, startup upgrade

Use **Flask-Migrate** (not raw Alembic): standard Flask-SQLAlchemy app, `flask db` CLI for
free. The deployed Neon DB has tables but no `alembic_version`, so:

1. Generate a baseline migration from current models against a fresh DB
   (`flask db init` + `flask db migrate -m "baseline"`), hand-review it (watch for SQLite
   autogen quirks vs Postgres).
2. Replace `db.create_all()` in `create_app` with a startup hook: if `alembic_version` is
   absent **and** app tables exist → `stamp(revision=<baseline>)`; then always `upgrade()`.
   Gate behind `AUTO_MIGRATE` env (default on). Wrap in try/except with logging so a failed
   migration produces a clear log line, not a silent 500 storm. Startup is the right hook:
   the Procfile runs gunicorn with the default single worker and Render's free tier has no
   pre-deploy phase.
3. Fresh dev DBs go through the same path (empty DB → `upgrade()` creates everything).
4. **Tests keep `db.create_all()`** — moved into the `app` fixture in `tests/conftest.py`.
   The suite currently relies on the factory calling it; removing it without this breaks
   every test.

### Decision 2 — CI: one GitHub Actions workflow, no coverage gate until Phase 4

`.github/workflows/ci.yml`: single job, Python matching `.python-version`, pip cache,
`ruff check` + `ruff format --check` + `pytest --cov=app --cov-report=term-missing`.
Ruff and pytest config live in a new `pyproject.toml`. Print coverage but do **not** fail
on it until Phase 4 lands the missing tests; then ratchet with `--cov-fail-under` set to
the achieved number minus a couple of points. No matrix, no tox.

### Decision 3 — routes.py: keep one blueprint, extract services

Do **not** split into multiple blueprints — endpoint names (`url_for('main.…')`) are used
across all 13 templates and renaming them is all risk, no user value. Instead extract pure
logic into `app/services/` (`routines.py`, `stats.py`), keeping view functions thin.
URLs, endpoint names, and templates untouched.

### Decision 4 — PWA scope: installable shell + static caching only

Ship `manifest.json`, icons, meta tags, and a small service worker (cache-first for
versioned static assets, network-first navigations with an offline fallback page).
**Out of scope**: Background Sync / IndexedDB offline log queueing — multi-session effort
with tricky conflict semantics, disproportionate for this app. Cheap middle ground included
instead: persist in-progress log form values to localStorage (already used for theme/unit
prefs) so a dropped connection doesn't lose a filled-in form.

---

## Phase 1 — Safety net: CI, linting, secrets hardening, logging

**Goal:** every subsequent change runs against automated checks, and the two production
foot-guns (SECRET_KEY fallback, Fernet coupling) can no longer cause silent data loss or
500s.

Tasks:

1. Add `pyproject.toml` with ruff config (rule set `E,F,W,I,B,UP`, target matching
   `.python-version`) and pytest config. Fix whatever ruff flags — expect mostly
   mechanical import-order fixes.
2. Add `.github/workflows/ci.yml` per Decision 2. Add `ruff` and `pytest-cov` to
   `requirements-dev.txt`.
3. **SECRET_KEY hard-fail in prod** (config.py:5-9): raise `RuntimeError` when `SECRET_KEY`
   is unset and a production signal is present (`DATABASE_URL` set to a non-SQLite URL, or
   the `RENDER` env var). Keep the warning fallback for local dev only.
4. **Fernet resilience** (app/models.py:95-117; settings route app/routes.py:~1040-1070;
   `resolve_api_key` in app/ai_generator.py:100-105): catch
   `cryptography.fernet.InvalidToken` at `get_key()`/`key_hint()` call sites. The Settings
   page must render "your stored key can't be decrypted — please re-enter it" instead of
   500ing; generation should fall back as if no user key exists, with a flash. Introduce an
   optional `FERNET_KEY` env var: `_fernet()` prefers it, falling back to the existing
   SHA-256(SECRET_KEY) derivation for backward compatibility. Document in the README that
   setting `FERNET_KEY` to the currently derived key **before** ever rotating `SECRET_KEY`
   preserves stored user keys.
5. **Logging**: configure `app.logger` in `create_app` (level from `LOG_LEVEL` env, stream
   handler suitable for Render logs). Add `logger.exception(...)` where errors are
   currently only flashed: AI generation failures in `generate`/`retry_program`,
   decryption failures, DB errors. No new dependency.
6. Fix **account enumeration** (app/routes.py:270, :274): replace the distinct
   "Username already exists" / "Email already registered" flashes with one generic
   "Username or email already in use".

Verification:
- CI workflow runs green on the branch.
- Booting with a Postgres `DATABASE_URL` and no `SECRET_KEY` raises (add a unit test).
- New test: Settings page renders (not 500) when the stored key is undecryptable
  (e.g. encrypt with one key, read with another).
- All existing tests pass; ruff clean.

## Phase 2 — Database integrity: migrations, indexes, cascades

**Goal:** schema changes reach the deployed Neon DB; the data model stops orphaning rows.
Highest-impact engineering fix; unblocks every future model change.

Tasks:

1. Add Flask-Migrate; `migrate.init_app(app, db)` in `app/__init__.py`. Generate and
   hand-review the baseline migration (Decision 1).
2. Replace `db.create_all()` (app/__init__.py:38-39) with the stamp-or-upgrade startup
   hook. **Simultaneously move `db.create_all()` into the `app` fixture in
   `tests/conftest.py` (~lines 15-21)** — required, or the whole suite breaks.
3. Second migration — indexes: `Workout.user_id` (app/models.py:32),
   `ExerciseLog.workout_id` (:49), and `user_id` on `UserProgression` (:145),
   `CustomExercise` (:65), `HiddenExercise` (:90), `RotationEntry` (:156).
   (`WorkoutSchedule` already gets one from its unique constraint.)
4. Third migration + model changes — relationships/cascades: add
   `cascade='all, delete-orphan'` relationships from `User` to the six tables currently
   linked only by bare FKs, and `Workout` → `ExerciseLog`. Simplify `delete_program`'s
   manual cleanup (app/routes.py:1028-1032) **only** where a relationship now covers it —
   the CustomExercise/HiddenExercise overlays are keyed by the `routine_type` *string*
   (`'ai-<id>'`), not an FK, so that part stays manual. Do not over-delete.
5. Update the README with the migration workflow (`flask db migrate` / `flask db upgrade`)
   and the one-time prod stamp behavior.

Verification:
- Fresh SQLite DB boots via `upgrade()` alone (no `create_all`).
- Simulated "existing prod DB": create tables with the old `create_all` code, boot the new
  code, confirm it stamps then upgrades (scripted check or test for the stamp logic).
- New test: deleting a user cascades (no orphaned Workout/ExerciseLog/etc. rows).
- Full suite + CI green. After deploy, Render logs show the stamp/upgrade line.

## Phase 3 — Robustness: rate limiting, crash fixes, AI-generation hardening

**Goal:** the app can't be brute-forced or have its shared API key drained; known latent
crashes are eliminated.

Tasks:

1. Add **Flask-Limiter** (in-memory storage — single gunicorn worker per Decision 1, so no
   Redis): `5/minute` on login and register (app/routes.py:235-296); `3/hour` on
   `/generate` **when the server key is used** — users with their own `UserApiKey` get an
   exemption or a much higher limit (burning their own key is their business).
2. Latent crash fixes:
   - Tolerant reps parsing in `ExerciseLog.get_reps_list` (app/models.py:51-54) — BWF reps
     come from free-form form input, so tokens like `"30s"` currently raise `ValueError`
     at *read* time. Skip or strip non-integer tokens. Same guard in
     `maybe_advance_progression` (app/routes.py:592).
   - `request.get_json(silent=True) or {}` in `plan_workout` (app/routes.py:829) and any
     sibling JSON endpoint that can raise on a malformed body; return 400, not 500.
3. **Timezone consistency** (app/routes.py:633-644): `Workout.date` is tz-aware UTC but the
   dashboard compares against `date.today()` (server-local). Do all comparisons in UTC
   (`datetime.now(timezone.utc).date()`). Note per-user timezone support as possible
   future work — do not build it now.
4. **AI generator** (app/ai_generator.py):
   - Inspect `response.stop_reason`: on `max_tokens`, surface "the response was truncated —
     try fewer training days or a shorter session"; on a refusal/empty content, surface
     that instead of the generic invalid-program message (current code at :165-174).
   - On JSON-validation failure, retry by **appending** the failed response and a
     correction instruction to `messages` instead of re-sending identical input (:142-174).
   - Switch to `client.messages.stream(...)` + `get_final_message()` — keeps the
     synchronous route shape while avoiding long non-streaming requests tripping
     proxy/idle timeouts (Procfile `--timeout 300` already accommodates).
5. Remove dead code: `progress()` pure-redirect route (app/routes.py:616-619 — first
   repoint any `url_for('main.progress')` in templates); always-None progression args in
   `_gym_style_exercise_view` (:327-328); empty conditional in
   `app/templates/generate.html:31`.

Verification:
- Test: 6th rapid login attempt returns 429 (enable the limiter in a dedicated test
  config — keep it disabled in the default `TestConfig` so the rest of the suite is
  unaffected).
- Test: an ExerciseLog with reps `"30s,8,8"` renders in progress/dashboard without crashing.
- Test: malformed JSON body to `/schedule/plan` returns 400, not 500.
- Test with mocked client: `stop_reason='max_tokens'` produces the truncation message.
- Full suite + CI green.

## Phase 4 — Test coverage, then targeted refactors

**Goal:** the newest features get tests *first*, then the worst code-quality debt is
refactored under that safety net. The tests-before-refactor ordering is deliberate — the
step-1 tests are the harness for steps 3-4.

Tasks:

1. New tests (new files `tests/test_dashboard.py`, `tests/test_schedule.py` or extend
   `tests/test_routes.py`):
   - `/dashboard` (app/routes.py:624) with seeded workouts including week/month boundary
     dates; assert the computed counts.
   - `/schedule` (:764), `save_rotation` (:812), `plan_workout` (:829) including the
     duplicate-date unique-constraint path, `unplan_workout` (:858) including another
     user's entry (403/404).
   - `/logout` (:299), exercise detail view (:305), `_today_plan` (:105).
   - One test class with `WTF_CSRF_ENABLED = True` proving the JSON endpoints require the
     CSRF header (covers the currently untested main.js coupling).
2. Set the CI coverage ratchet (`--cov-fail-under=<achieved minus ~2>`).
3. Create `app/services/routines.py`:
   - Single `routine_display_name()` — dedupes app/routes.py:143-152, the inner
     `_routine_label` at :673-681, and the inline comprehension at :796-799.
   - Single `active_ai_programs(user)` query — dedupes :180-182, :669-671, :765-767.
   - Unify BWF set parsing with `parse_gym_sets` (:562-565 vs :521-531).
4. Create `app/services/stats.py`: rewrite the `dashboard()` aggregation
   (app/routes.py:622-756) in SQL (`func.count` grouped by week/month) instead of loading
   every workout into Python, and replace the N+1 weight-trend loop (:714-741) with one
   query over `ExerciseLog` joined to `Workout`, grouped by exercise. The dashboard view
   should shrink to roughly 30 lines.
5. Move the `exercise_name.endswith('Progression')` branch out of
   `app/templates/workout_detail.html:19` into a flag computed in the view/service.

Verification:
- Coverage report shows the previously untested routes covered; ratchet active in CI.
- Dashboard output identical before/after the refactor (step-1 tests are the harness).
- Confirm the N+1 is gone (query-count assertion or SQLAlchemy echo spot-check).
- Full suite + CI green.

## Phase 5 — Frontend quality: extract JS, dedupe templates, accessibility, error states

**Goal:** the frontend becomes maintainable and accessible, and the plumbing Phase 6
depends on (cache busting, external/vendored JS) lands.

Tasks:

1. **Cache busting** (prerequisite for the Phase 6 service worker): a `static_url()`
   template helper / context processor appending `?v=<content hash or version>` to static
   asset URLs; use it in `base.html` and per-page asset tags.
2. Extract inline JS: the Chart.js block in `app/templates/dashboard.html` (~165 lines,
   lines 3-173) → `app/static/js/dashboard.js`; the drag/calendar logic in
   `app/templates/schedule.html` (~155 lines, lines 79-232) → `app/static/js/schedule.js`.
   Pass server data via `<script type="application/json">` blocks (`|tojson`) read by the
   static scripts.
3. Consistent fetch handling: shared `fetchJSON()` helper (in main.js) with error display,
   replacing the unhandled fetches (old schedule.html:143-153, :202-231; DELETE response
   unchecked at :212). Guard the CSRF-meta lookup (old schedule.html:80) so a missing meta
   degrades gracefully instead of killing the whole script. Add a pending indicator to the
   AJAX log submit (app/static/js/main.js:152-179).
4. Template dedup via macros in `app/templates/_macros.html`:
   - Progression card (dashboard.html:247-261 ≈ progress.html:10-25).
   - Workout card (dashboard.html:270-277 ≈ progress.html:33-39).
   - Exercise-card header (home.html:95-135 ≈ preview_program.html:17-30).
   - Unified log form — the two ~80%-identical forms in home.html (:177-222 vs :239-272),
     parametrized on weighted/BWF. Careful: main.js builds set-row HTML as a template
     string (main.js:133-141) that must stay in sync with the rendered markup.
5. Accessibility: `aria-expanded`/`aria-controls` on the accordion toggles
   (home.html:95-98, wired in main.js); `aria-label` on icon-only buttons (remove `×`,
   timer `−30s/▶/↺`, drag handle `⠿`); text alternative for the canvas charts
   (visually-hidden summary or `role="img"` + label).
6. Single-source shared constants: emit a small JSON config in base.html for
   `LBS_PER_KG` (main.js:14 vs the 0.453592 in routes.py:736) and rest periods
   (routes.py:498 vs main.js:201-204); consolidate the equipment icons duplicated between
   `_macros.html` and `EQ_ICONS` in main.js:23-27 (render server-side where possible).
7. **Vendor Chart.js locally** (replaces the CDN tag without SRI, dashboard.html:4;
   local hosting is also required for Phase 6 offline caching). Replace the private
   `Chart.instances` API usage (:170) with a module-level chart registry.

Verification:
- Manual click-through: dashboard charts (both themes), schedule (drag-reorder, plan,
  unplan, and a devtools-offline failure showing an error message), home logging for both
  routine types including add/remove set.
- Lighthouse accessibility pass on home + dashboard (target ≥ 90).
- Hard refresh confirms `?v=` busting; changing a file changes the URL.
- Full suite + CI green (template changes can break tests that assert markup).

## Phase 6 — PWA: installable, offline-tolerant shell

**Goal:** the app installs to a phone home screen and stays usable on flaky gym wifi.
The headline user-facing win; last because it depends on Phase 5's cache busting and
vendored assets. **Do not reorder the service worker ahead of Phase 5** — SW caching
without cache busting causes stale-asset bugs.

Tasks:

1. `app/static/manifest.json`: name/short_name, icons derived from
   `app/static/img/logo.svg` (192px and 512px PNGs, plus maskable), `display: standalone`,
   theme/background colors consistent with both light and dark CSS themes. Link it in
   base.html with `theme-color` and `apple-mobile-web-app-*` metas.
2. `app/static/sw.js`: versioned cache name tied to the Phase 5 asset version; cache-first
   for `/static/*`; network-first for navigations with fallback to a cached `/offline`
   page (new minimal route + template); never intercept `/generate`, auth routes, or
   non-GET requests.
3. SW registration in main.js with update handling (new version → activate on next load;
   optionally a "refresh for update" toast).
4. localStorage draft persistence for the workout log forms: save on input, restore on
   load, clear on successful submit (Decision 4's "didn't lose my set" win).
5. README section: how the SW/cache version is bumped when assets change.

Verification:
- Lighthouse PWA installability checks pass.
- Devtools offline: previously visited pages render from cache; unvisited navigations show
  the offline fallback; static assets served from cache.
- Fill a log form, kill the network, reload → form values restored.
- After deploy, Render serves `manifest.json` and `sw.js` with correct MIME types and the
  SW activates on a real phone.

---

## Ordering rationale

Phase 1 (safety net) enables everything after it. Phase 2 (migrations) is the
highest-impact fix and blocks the index/cascade schema work. Phase 3 removes exploitable
and crashing behavior. Phase 4 pairs the missing tests with the refactors they de-risk.
Phase 5 is prerequisite plumbing for Phase 6. Phase 6 is the headline user win.

If a user-visible win is wanted sooner, the manifest + registration (Phase 6 tasks 1 and 3,
without SW caching) can be cherry-picked after Phase 3 — but the service worker itself must
wait for Phase 5's cache busting.
