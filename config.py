import os
import warnings


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        # A managed platform (Render) or a non-SQLite DATABASE_URL means we're
        # running for real — refuse to boot on the insecure development key.
        _database_url = os.environ.get('DATABASE_URL', '')
        _in_production = bool(os.environ.get('RENDER')) or (
            bool(_database_url) and not _database_url.startswith('sqlite')
        )
        if _in_production:
            raise RuntimeError(
                'SECRET_KEY must be set in production. Refusing to start with an '
                'insecure development key.'
            )
        SECRET_KEY = 'dev-only-insecure-key'
        warnings.warn(
            'SECRET_KEY is not set — using an insecure development key. '
            'Set the SECRET_KEY environment variable in production.',
            stacklevel=2,
        )

    # Optional explicit key for encrypting stored user API keys. When set, it
    # decouples the cipher from SECRET_KEY so SECRET_KEY can be rotated without
    # bricking stored keys. Falls back to a SECRET_KEY-derived key when unset.
    FERNET_KEY = os.environ.get('FERNET_KEY')

    # Server-wide default key for AI program generation. Optional — users can
    # also store their own key in Settings, which takes precedence.
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

    # Outbound email (password resets, reminders). All optional: with neither
    # BREVO_API_KEY nor MAIL_SERVER set, the app logs messages instead of
    # sending (dev mode). BREVO_API_KEY (an 'xkeysib-…' key) uses Brevo's
    # HTTPS API and is the backend that works on Render, which blocks
    # outbound SMTP ports; MAIL_SERVER is plain SMTP for any other relay.
    BREVO_API_KEY = os.environ.get('BREVO_API_KEY')
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_FROM = os.environ.get('MAIL_FROM')

    # Absolute base URL used for links in emails (e.g. https://app.onrender.com).
    # Set it in production so emailed links can't be steered by a spoofed Host
    # header; local dev falls back to the request host.
    APP_BASE_URL = os.environ.get('APP_BASE_URL')

    # Shared secret an external cron must present (Authorization: Bearer …) to
    # trigger /tasks/send_reminders. Unset = the endpoint 404s (feature off).
    CRON_SECRET = os.environ.get('CRON_SECRET')

    # Optional access code gating the shared ANTHROPIC_API_KEY: when set, users
    # must enter it once in Settings before AI generation uses the shared key
    # (their own saved key always works). Unset = shared key open to everyone.
    SHARED_KEY_ACCESS_CODE = os.environ.get('SHARED_KEY_ACCESS_CODE')

    _db_uri = os.environ.get('DATABASE_URL') or 'sqlite:///nofluff.db'
    # SQLAlchemy 2.x requires 'postgresql://' — Render/Neon provide 'postgres://'
    if _db_uri.startswith('postgres://'):
        _db_uri = _db_uri.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = _db_uri

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Neon (and Render's proxy) drop idle/stale connections, which surfaces as
    # 'SSL error: decryption failed or bad record mac'. Verify connections
    # before use and recycle them before the platform kills them.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
