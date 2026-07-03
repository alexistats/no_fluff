import os
import warnings


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        SECRET_KEY = 'dev-only-insecure-key'
        warnings.warn(
            'SECRET_KEY is not set — using an insecure development key. '
            'Set the SECRET_KEY environment variable in production.',
            stacklevel=2,
        )

    # Server-wide default key for AI program generation. Optional — users can
    # also store their own key in Settings, which takes precedence.
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

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
