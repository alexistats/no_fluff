# NoFluff

**The no fluff workout app.** A mobile-friendly workout tracker built with Flask — no ads, no upsells, no social feed. Supports two built-in routines plus AI-generated ones:

- **BWF Routine** — the [Bodyweight Fitness Recommended Routine](https://www.reddit.com/r/bodyweightfitness/wiki/kb/recommended_routine/), with automatic progression tracking (e.g., scapular pulls → arch hangs → negative pull-ups → pull-ups)
- **Gym Routine** — a machine/free-weight routine with per-set weight and rep logging
- **AI Programs** — describe your goal (climbing, a 5k, ringette…), equipment, and availability, and Claude generates a personalized program with all the same logging features

## Features

- **AI program generator** — preview the generated program, regenerate with feedback ("less volume", "no overhead pressing"), then save it as a routine alongside BWF/Gym; uses a shared server key or your own Claude API key (stored encrypted)
- **Quickstart** — the app opens to your last-used routine with a one-tap "Start Workout" button
- **Workout sessions** — start a workout, log exercises as you go, end when done (empty workouts are discarded)
- **Routine editing (Gym)** — add your own exercises (name, sets, reps, equipment) or remove built-in ones, right from the home page; removals are restorable
- **Flexible sets** — add or remove sets on any logging form (1–10), for light days and crazy days alike
- **Progression system (BWF)** — hit 3 sets of 8+ reps and the app advances you to the next exercise progression automatically
- **Weight tracking (Gym)** — log weight × reps per set; your last session's numbers are pre-filled the next time
- **kg/lbs toggle** — switch units on the fly for machines labelled differently; preference is remembered, conversions apply to inputs and your last-session summary
- **Plate calculator (barbell exercises)** — tap plates to load a visual barbell, see the total including the bar, and fill it into any set with one tap; plate denominations follow the kg/lbs toggle
- **Rest timer** — built-in 60/90/120s countdown with vibration on completion
- **Activity dashboard** — workout frequency, per-routine breakdown, most-trained exercises, and strength trends (charts), plus current progression levels and recent history
- **Scheduling & rotation** — set a preferred routine rotation and plan workouts on a 2-week calendar; the home page surfaces today's planned or next-in-rotation workout
- **Installable PWA** — add it to your phone's home screen; the app shell and assets are cached, in-progress log forms are saved locally, and there's a graceful offline page for flaky gym Wi-Fi
- **Mobile-first UI** — responsive layout designed to be used at the gym from a phone
- **Dark mode** — light/dark theme toggle in the header; defaults to your system preference and remembers your choice

## Tech stack

Flask 3 · Flask-SQLAlchemy · Flask-Migrate (Alembic) · Flask-Login · Flask-WTF (CSRF) · Flask-Limiter · Jinja2 · vanilla JS + a service worker · Chart.js (vendored) · SQLite (dev) / PostgreSQL (production)

Tooling: ruff (lint + format) and pytest, both enforced in GitHub Actions CI.

## Running locally

```bash
# 1. Clone and enter the repo
git clone https://github.com/alexistats/no_fluff.git
cd no_fluff

# 2. Create a virtualenv and install dependencies
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Run the dev server
python run.py
```

The app starts on `http://localhost:5000` with a local SQLite database (`nofluff.db`), created automatically on first run.

The Python version is pinned in `.python-version` (3.13) — pyenv/uv pick it up locally, and Render uses it to select the runtime. Newer Pythons (3.14+) don't have prebuilt wheels for all pinned dependencies yet.

### Configuration

| Environment variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy database URL (`postgres://` URLs are normalized automatically) | `sqlite:///nofluff.db` |
| `SECRET_KEY` | Flask session/CSRF signing key — **required in production** (the app refuses to start without it when `RENDER` or a non-SQLite `DATABASE_URL` is set) | insecure dev key (warns, local only) |
| `FERNET_KEY` | Optional key (a `Fernet.generate_key()` value) for encrypting stored user API keys. When unset, one is derived from `SECRET_KEY`. Set it to decouple the two — see the note below. | derived from `SECRET_KEY` |
| `ANTHROPIC_API_KEY` | Shared Claude API key for the AI program generator — optional; users can also save their own key in Settings (stored encrypted, takes precedence) | unset (feature prompts for a user key) |
| `LOG_LEVEL` | Log level for the app logger (`DEBUG`, `INFO`, `WARNING`, …) | `INFO` |

> **Rotating `SECRET_KEY`:** stored user API keys are encrypted with a key derived from `SECRET_KEY` by default, so rotating `SECRET_KEY` makes them undecryptable (the Settings page then prompts the user to re-enter their key rather than erroring). To rotate `SECRET_KEY` while preserving stored keys, first set `FERNET_KEY` to the currently derived value: `python -c "import base64,hashlib,os; print(base64.urlsafe_b64encode(hashlib.sha256(os.environ['SECRET_KEY'].encode()).digest()).decode())"`.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

Linting and formatting (also enforced in CI):

```bash
ruff check .
ruff format --check .
```

The suite (~70 tests, ~88% coverage) covers progression rules, gym set parsing, the full register → login → workout → log flow, permission checks, the dashboard/schedule/rotation endpoints, secrets hardening, rate limiting, AI-generation error handling, and the PWA plumbing. A CI coverage floor (`--cov-fail-under`) guards against regressions.

## Database migrations

Schema changes are managed with [Flask-Migrate](https://flask-migrate.readthedocs.io/) (Alembic). After changing a model:

```bash
export FLASK_APP="app:create_app"
flask db migrate -m "describe the change"   # autogenerate a migration
flask db upgrade                            # apply it locally
```

Review the generated file in `migrations/versions/` before committing it.

On startup the app brings the database up to date automatically (equivalent to `flask db upgrade`), so deploys need no manual migration step. A database created before migrations existed (only the original `db.create_all()` schema) is stamped at the baseline revision on first boot and then upgraded. Set `AUTO_MIGRATE=0` to disable the startup migration and run `flask db upgrade` yourself.

## Deployment (Render + Neon)

The app is set up for a free-tier deployment:

1. **Neon** — create a free PostgreSQL project at [neon.tech](https://neon.tech) and copy the connection string
2. **Render** — create a Web Service at [render.com](https://render.com) pointed at this repo (`main` branch):
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --timeout 300` — set this explicitly in the dashboard (Render pre-fills a generic `gunicorn app:app` that won't work with this app's factory pattern; the `--timeout 300` gives AI program generation room to finish)
   - Python version: auto-detected from `.python-version` (don't set `PYTHON_VERSION` manually)
   - Environment variables: `DATABASE_URL` (Neon connection string) and `SECRET_KEY` (e.g., `python -c "import secrets; print(secrets.token_hex(32))"`)

The schema is created and kept up to date automatically on startup (see [Database migrations](#database-migrations)). Note that both free tiers sleep when idle — the first request after a quiet period takes ~30–60s.

## Progressive Web App

NoFluff is installable to a phone home screen (`static/manifest.json` + icons) and stays usable on flaky connections via a service worker (`static/js/sw.js`, served at `/sw.js` for root scope):

- **Static assets** are cache-first — combined with the `?v=<hash>` cache-busting, updated files are refetched automatically.
- **Page navigations** are network-first and fall back to a cached `/offline` page when there's no connection. Nothing authenticated is cached.
- **Log forms** persist to `localStorage` as you type, so a dropped connection or reload doesn't lose an in-progress set (cleared once the set is logged).

When you change cached assets and want clients to drop the old cache, bump `VERSION` in `static/js/sw.js` (e.g. `'v1'` → `'v2'`); the new worker deletes older caches on activation.

## Project structure

```
app/
  __init__.py          # App factory: DB, migrate, login, CSRF, rate limiter, logging, cache-busting
  models.py            # User, Workout, ExerciseLog, progressions, custom/hidden exercises, AI programs, schedule…
  routes.py            # Views + workout/progression logic, scheduling, AI generation, PWA endpoints
  ai_generator.py      # Claude program generation (structured output + validation)
  services/            # routines.py (labels/AI-program helpers), stats.py (dashboard SQL aggregation)
  static/
    css/style.css      # Responsive styles
    js/main.js         # Rest timer, set inputs, kg/lbs converter, drafts, service-worker registration
    js/dashboard.js    # Dashboard charts (Chart.js)
    js/schedule.js     # Rotation drag-sort + calendar planning
    js/sw.js           # Service worker (served at /sw.js)
    js/vendor/         # Vendored Chart.js
    manifest.json      # PWA manifest
    img/               # Logo + PWA icons
  templates/           # Jinja2 templates (incl. _macros.html, offline.html)
migrations/            # Flask-Migrate / Alembic migrations
data/
  routine_data.json    # BWF routine structure
  progressions.json    # BWF progression levels per exercise
  gym_routine.json     # Gym routine structure (Push/Pull/Legs/Core)
docs/IMPROVEMENTS.md   # Log of engineering-improvement work
tests/                 # Pytest suite
config.py              # Environment-driven configuration
run.py                 # Dev entry point
Procfile               # Production entry point (gunicorn)
```

## Customizing routines

Routines are plain JSON in `data/` — edit `gym_routine.json` to add or swap exercises (set `"weighted": true` for anything that should track weight). Changes take effect on restart; no database migration needed.
