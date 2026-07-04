"""Rate limiting on auth (the default TestConfig disables it)."""

import pytest

from app import create_app, db, limiter
from config import Config


class RateLimitConfig(Config):
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = True
    ANTHROPIC_API_KEY = None


@pytest.fixture
def rl_client():
    app = create_app(RateLimitConfig)
    with app.app_context():
        db.create_all()
        limiter.reset()
    yield app.test_client()
    with app.app_context():
        db.drop_all()
        limiter.reset()


def test_login_post_is_rate_limited(rl_client):
    codes = [
        rl_client.post('/login', data={'username': 'x', 'password': 'y'}).status_code
        for _ in range(6)
    ]
    # 5/minute — the first five go through, the sixth is blocked.
    assert codes[-1] == 429
    assert codes.count(429) == 1
