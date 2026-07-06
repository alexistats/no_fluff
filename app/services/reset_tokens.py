"""Signed, expiring password-reset tokens — no database storage needed.

The token binds a fragment of the user's current password hash, so it becomes
invalid the moment the password changes (single-use without a token table).
"""

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db
from app.models import User

RESET_TOKEN_MAX_AGE = 3600  # seconds — 1 hour


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='password-reset')


def generate_reset_token(user):
    return _serializer().dumps({'uid': user.id, 'ph': (user.password_hash or '')[-12:]})


def verify_reset_token(token):
    """The User a valid token belongs to, or None (bad, expired, or already used)."""
    try:
        data = _serializer().loads(token, max_age=RESET_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get('uid'))
    if user is None or (user.password_hash or '')[-12:] != data.get('ph'):
        return None
    return user
