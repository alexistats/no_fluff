"""Phase 3: forgot-password flow and the email service."""

import re

import pytest

from app import create_app, db, limiter
from app.services import email as email_service
from app.services import reset_tokens
from config import Config


@pytest.fixture
def outbox(monkeypatch):
    """Capture emails the routes try to send."""
    sent = []

    def fake_send(to, subject, text, html=None):
        sent.append({'to': to, 'subject': subject, 'text': text})
        return True

    monkeypatch.setattr('app.routes.send_email', fake_send)
    return sent


def _register(client):
    client.post(
        '/register',
        data={
            'username': 'resetuser',
            'email': 'reset@example.com',
            'password': 'originalpass123',
        },
    )


def _request_reset(client, email='reset@example.com'):
    return client.post('/forgot_password', data={'email': email}, follow_redirects=True)


def _login(client, password):
    data = {'username': 'resetuser', 'password': password}
    return client.post('/login', data=data, follow_redirects=True)


def _reset_path(outbox):
    url = re.search(r'https?://\S+', outbox[-1]['text']).group()
    return url.replace('http://localhost', '')


# ── The flow ───────────────────────────────────────────────────────


def test_login_page_links_to_forgot_password(client):
    assert b'/forgot_password' in client.get('/login').data


def test_unknown_email_same_message_and_no_send(client, outbox):
    resp = _request_reset(client, 'nobody@example.com')
    assert b'If that email is registered' in resp.data
    assert outbox == []


def test_reset_flow_end_to_end(client, outbox):
    _register(client)
    resp = _request_reset(client)
    assert b'If that email is registered' in resp.data
    assert len(outbox) == 1 and outbox[0]['to'] == 'reset@example.com'

    path = _reset_path(outbox)
    assert client.get(path).status_code == 200

    resp = client.post(
        path,
        data={'password': 'brandnewpass456', 'confirm_password': 'brandnewpass456'},
        follow_redirects=True,
    )
    assert b'Password updated' in resp.data

    resp = _login(client, 'originalpass123')
    assert b'Invalid username or password' in resp.data
    resp = _login(client, 'brandnewpass456')
    assert b'Logout' in resp.data


def test_token_stops_working_after_use(client, outbox):
    _register(client)
    _request_reset(client)
    path = _reset_path(outbox)
    client.post(path, data={'password': 'brandnewpass456', 'confirm_password': 'brandnewpass456'})

    resp = client.get(path, follow_redirects=True)
    assert b'invalid or has expired' in resp.data


def test_expired_token_rejected(client, outbox, monkeypatch):
    _register(client)
    _request_reset(client)
    path = _reset_path(outbox)

    monkeypatch.setattr(reset_tokens, 'RESET_TOKEN_MAX_AGE', -1)
    resp = client.get(path, follow_redirects=True)
    assert b'invalid or has expired' in resp.data


def test_tampered_token_rejected(client):
    resp = client.get('/reset_password/not-a-real-token', follow_redirects=True)
    assert b'invalid or has expired' in resp.data


def test_short_or_mismatched_passwords_rejected(client, outbox):
    _register(client)
    _request_reset(client)
    path = _reset_path(outbox)

    resp = client.post(
        path, data={'password': 'short', 'confirm_password': 'short'}, follow_redirects=True
    )
    assert b'at least 8 characters' in resp.data
    resp = client.post(
        path,
        data={'password': 'brandnewpass456', 'confirm_password': 'different456'},
        follow_redirects=True,
    )
    assert b'Passwords do not match' in resp.data

    # Neither attempt changed the password.
    resp = _login(client, 'originalpass123')
    assert b'Logout' in resp.data


def test_authenticated_users_are_redirected_away(logged_in_client):
    assert logged_in_client.get('/forgot_password').status_code == 302
    assert logged_in_client.get('/reset_password/whatever').status_code == 302


# ── Rate limiting (default TestConfig disables it) ─────────────────


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


def test_forgot_password_post_is_rate_limited(rl_client):
    codes = [
        rl_client.post('/forgot_password', data={'email': 'x@example.com'}).status_code
        for _ in range(4)
    ]
    # 3/hour — the fourth request is blocked.
    assert codes[-1] == 429
    assert codes.count(429) == 1


# ── The email service itself ───────────────────────────────────────


def test_send_email_console_backend_logs_instead(app, caplog):
    import logging

    caplog.set_level(logging.INFO)
    with app.app_context():
        assert email_service.send_email('a@example.com', 'Console subj', 'Body') is True
    assert 'Console subj' in caplog.text


class _FakeSMTP:
    sent = []
    fail = False

    def __init__(self, server, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        if _FakeSMTP.fail:
            raise OSError('boom')
        _FakeSMTP.sent.append(message)


def test_send_email_smtp_backend(app, monkeypatch):
    _FakeSMTP.sent, _FakeSMTP.fail = [], False
    monkeypatch.setattr('app.services.email.smtplib.SMTP', _FakeSMTP)
    with app.app_context():
        app.config.update(MAIL_SERVER='smtp.example.com', MAIL_USERNAME='u', MAIL_PASSWORD='p')
        assert email_service.send_email('to@example.com', 'Hi', 'Body') is True
    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]['To'] == 'to@example.com'


def test_send_email_smtp_failure_returns_false(app, monkeypatch):
    _FakeSMTP.sent, _FakeSMTP.fail = [], True
    monkeypatch.setattr('app.services.email.smtplib.SMTP', _FakeSMTP)
    with app.app_context():
        app.config.update(MAIL_SERVER='smtp.example.com')
        assert email_service.send_email('to@example.com', 'Hi', 'Body') is False


class _FakeAPIResponse:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_send_email_brevo_api_backend_takes_precedence(app, monkeypatch):
    import json

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured['url'] = request.full_url
        captured['api_key'] = request.get_header('Api-key')
        captured['payload'] = json.loads(request.data)
        return _FakeAPIResponse()

    monkeypatch.setattr('app.services.email.urllib.request.urlopen', fake_urlopen)
    with app.app_context():
        # MAIL_SERVER is also set — the HTTPS API must win (SMTP is blocked on Render).
        app.config.update(
            BREVO_API_KEY='xkeysib-test',
            MAIL_SERVER='smtp.example.com',
            MAIL_FROM='NoFluff <no-reply@example.com>',
        )
        assert email_service.send_email('to@example.com', 'Hi', 'Body') is True

    assert captured['url'] == email_service.BREVO_API_URL
    assert captured['api_key'] == 'xkeysib-test'
    assert captured['payload']['sender'] == {'email': 'no-reply@example.com', 'name': 'NoFluff'}
    assert captured['payload']['to'] == [{'email': 'to@example.com'}]
    assert captured['payload']['textContent'] == 'Body'


def test_send_email_brevo_api_failure_returns_false(app, monkeypatch):
    import urllib.error

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError('boom')

    monkeypatch.setattr('app.services.email.urllib.request.urlopen', fake_urlopen)
    with app.app_context():
        app.config.update(BREVO_API_KEY='xkeysib-test', MAIL_FROM='no-reply@example.com')
        assert email_service.send_email('to@example.com', 'Hi', 'Body') is False
