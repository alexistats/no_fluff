"""Phase 1 hardening: SECRET_KEY, Fernet resilience, auth error messages."""

import importlib
import os

import pytest

import config
from app import ai_generator, db
from app.models import User, UserApiKey


@pytest.fixture(autouse=True)
def _restore_config_module():
    """Reloading config mutates the module — restore a good state afterwards."""
    yield
    os.environ['SECRET_KEY'] = 'test-secret-key'
    importlib.reload(config)


# ── SECRET_KEY hard-fail in production ──────────────────────────────


def test_missing_secret_key_in_production_raises(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@host/db')
    with pytest.raises(RuntimeError, match='SECRET_KEY must be set'):
        importlib.reload(config)


def test_missing_secret_key_in_dev_only_warns(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.warns(UserWarning):
        importlib.reload(config)
    assert config.Config.SECRET_KEY == 'dev-only-insecure-key'


# ── Fernet resilience: undecryptable stored key ─────────────────────


def test_settings_page_survives_undecryptable_key(app, logged_in_client):
    with app.app_context():
        user = User.query.filter_by(username='testuser').first()
        db.session.add(
            UserApiKey(
                user_id=user.id,
                provider='anthropic',
                encrypted_key='not-a-valid-fernet-token',
            )
        )
        db.session.commit()

    page = logged_in_client.get('/settings')
    assert page.status_code == 200
    assert b"can't be decrypted" in page.data


def test_resolve_api_key_falls_back_when_undecryptable(app, logged_in_client):
    app.config['ANTHROPIC_API_KEY'] = 'server-key'
    with app.app_context():
        user = User.query.filter_by(username='testuser').first()
        db.session.add(UserApiKey(user_id=user.id, provider='anthropic', encrypted_key='garbage'))
        db.session.commit()
        assert ai_generator.resolve_api_key(user) == 'server-key'


# ── Account enumeration on register ─────────────────────────────────


def test_register_does_not_reveal_which_field_is_taken(client):
    client.post(
        '/register',
        data={'username': 'alice', 'email': 'alice@example.com', 'password': 'password123'},
    )

    dup_username = client.post(
        '/register',
        data={'username': 'alice', 'email': 'other@example.com', 'password': 'password123'},
        follow_redirects=True,
    )
    dup_email = client.post(
        '/register',
        data={'username': 'bob', 'email': 'alice@example.com', 'password': 'password123'},
        follow_redirects=True,
    )

    assert b'Username or email already in use' in dup_username.data
    assert b'Username or email already in use' in dup_email.data
    assert b'Username already exists' not in dup_username.data
    assert b'Email already registered' not in dup_email.data
