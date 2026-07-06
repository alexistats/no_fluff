"""Phase 4: reminder settings and the cron-triggered /tasks/send_reminders."""

from datetime import date

import pytest

from app.models import User

SECRET = 'cron-secret-for-tests'


@pytest.fixture
def outbox(monkeypatch):
    sent = []

    def fake_send(to, subject, text, html=None):
        sent.append({'to': to, 'subject': subject, 'text': text})
        return True

    monkeypatch.setattr('app.routes.send_email', fake_send)
    return sent


def _enable_reminders(client, time='00:00', tz_offset='0'):
    # '00:00' with UTC offset 0 means "always due today" — deterministic in tests.
    return client.post(
        '/settings',
        data={
            'action': 'reminders',
            'reminder_enabled': 'on',
            'reminder_time': time,
            'tz_offset_minutes': tz_offset,
        },
        follow_redirects=True,
    )


def _plan_today(client, routine='gym'):
    return client.post(
        '/schedule/plan', json={'date': date.today().isoformat(), 'routine_type': routine}
    )


def _fire(client, secret=SECRET):
    return client.post('/tasks/send_reminders', headers={'Authorization': f'Bearer {secret}'})


# ── Guarding the endpoint ──────────────────────────────────────────


def test_endpoint_hidden_when_unconfigured(client):
    assert client.post('/tasks/send_reminders').status_code == 404


def test_wrong_secret_is_forbidden(app, client):
    app.config['CRON_SECRET'] = SECRET
    assert _fire(client, 'wrong').status_code == 403


# ── The reminder logic ─────────────────────────────────────────────


def test_sends_when_due_and_is_idempotent(logged_in_client, app, outbox):
    client = logged_in_client
    app.config['CRON_SECRET'] = SECRET
    _enable_reminders(client)
    _plan_today(client)

    resp = _fire(client)
    assert resp.get_json() == {'sent': 1, 'skipped': 0}
    assert outbox[0]['to'] == 'test@example.com'
    assert outbox[0]['subject'] == 'Workout today: Gym'

    # Second run the same day: stamped, nothing sent.
    resp = _fire(client)
    assert resp.get_json()['sent'] == 0
    assert len(outbox) == 1
    with app.app_context():
        assert User.query.first().last_reminded_on == date.today()


def test_not_sent_before_the_chosen_time(logged_in_client, app, outbox):
    client = logged_in_client
    app.config['CRON_SECRET'] = SECRET
    # Local clock pinned 12h behind UTC: 23:59 local is always in the future.
    _enable_reminders(client, time='23:59', tz_offset='-720')
    _plan_today(client)

    assert _fire(client).get_json() == {'sent': 0, 'skipped': 1}
    assert outbox == []


def test_not_sent_without_a_planned_workout(logged_in_client, app, outbox):
    client = logged_in_client
    app.config['CRON_SECRET'] = SECRET
    _enable_reminders(client)

    assert _fire(client).get_json() == {'sent': 0, 'skipped': 1}
    assert outbox == []


def test_users_with_reminders_off_are_not_considered(logged_in_client, app, outbox):
    client = logged_in_client
    app.config['CRON_SECRET'] = SECRET
    _plan_today(client)  # planned workout but reminders never enabled

    assert _fire(client).get_json() == {'sent': 0, 'skipped': 0}
    assert outbox == []


def test_settings_persist_reminder_preferences(logged_in_client, app):
    resp = _enable_reminders(logged_in_client, time='06:30', tz_offset='-240')
    assert b'Reminder settings saved' in resp.data
    with app.app_context():
        user = User.query.first()
        assert user.reminder_enabled is True
        assert user.reminder_time == '06:30'
        assert user.tz_offset_minutes == -240


def test_invalid_time_and_offset_are_ignored(logged_in_client, app):
    logged_in_client.post(
        '/settings',
        data={
            'action': 'reminders',
            'reminder_enabled': 'on',
            'reminder_time': '25:99',
            'tz_offset_minutes': '99999',
        },
    )
    with app.app_context():
        user = User.query.first()
        assert user.reminder_time in (None, '07:00')  # column default, not garbage
        assert (user.tz_offset_minutes or 0) == 0
