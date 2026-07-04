import hashlib
import json
import logging
import os

from flask import Flask, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
csrf = CSRFProtect()
migrate = Migrate()
# In-memory storage is fine for a single gunicorn worker (see Procfile).
limiter = Limiter(key_func=get_remote_address, storage_uri='memory://')

# Revision of the baseline migration — the schema as it existed before the
# migration framework was added. Databases created by the old db.create_all()
# are stamped here on first boot, then upgraded to head.
BASELINE_REVISION = '0001_baseline'


_static_hashes = {}


def _static_version(app, filename):
    """Short content hash of a static file, cached by mtime, for cache-busting."""
    path = os.path.join(app.static_folder, filename)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _static_hashes.get(filename)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, 'rb') as f:
        digest = hashlib.md5(f.read()).hexdigest()[:8]  # noqa: S324 (cache key, not security)
    _static_hashes[filename] = (mtime, digest)
    return digest


def _register_static_url(app):
    """Expose static_url(filename) -> '/static/<file>?v=<hash>' to templates.

    The version query string changes when the file changes, so browsers (and
    the Phase 6 service worker) refetch updated assets instead of serving stale.
    """

    @app.context_processor
    def _static_url_processor():
        def static_url(filename):
            url = url_for('static', filename=filename)
            version = _static_version(app, filename)
            return f'{url}?v={version}' if version else url

        return {'static_url': static_url}


def _configure_logging(app):
    """Send app.logger to stdout at LOG_LEVEL (default INFO) for Render logs."""
    level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    app.logger.setLevel(level)
    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
        )
        app.logger.addHandler(handler)


def _run_migrations(app):
    """Bring the schema up to date on startup — run.py is bypassed under gunicorn.

    Databases that predate the migration framework have the baseline tables but
    no alembic_version row; stamp them at the baseline first so Alembic doesn't
    try to re-create existing tables, then upgrade to head.
    """
    from flask_migrate import stamp, upgrade
    from sqlalchemy import inspect

    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations')
    if not os.path.isdir(migrations_dir):
        app.logger.warning('No migrations directory found; skipping startup migration.')
        return
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            pre_migration = not inspector.has_table('alembic_version') and inspector.has_table(
                'user'
            )
            if pre_migration:
                app.logger.info('Stamping existing database at baseline %s', BASELINE_REVISION)
                stamp(revision=BASELINE_REVISION)
            upgrade()
    except Exception:
        app.logger.exception('Startup database migration failed')


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    _configure_logging(app)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    # render_as_batch lets SQLite (dev) handle ALTER-style migrations too.
    migrate.init_app(app, db, render_as_batch=True)
    limiter.init_app(app)
    _register_static_url(app)

    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

    with open(os.path.join(data_dir, 'routine_data.json')) as f:
        app.config['ROUTINE_DATA'] = json.load(f)

    with open(os.path.join(data_dir, 'progressions.json')) as f:
        app.config['PROGRESSION_DATA'] = json.load(f)

    with open(os.path.join(data_dir, 'gym_routine.json')) as f:
        app.config['GYM_ROUTINE_DATA'] = json.load(f)

    from app.routes import main

    app.register_blueprint(main)

    # Tests create their schema in the fixture; everywhere else, migrate on boot.
    if not app.testing and os.environ.get('AUTO_MIGRATE', '1') != '0':
        _run_migrations(app)

    return app
