"""Phase 4: the iCalendar feed — builder unit tests and the tokenized route."""

from datetime import date
from types import SimpleNamespace

from app.models import User
from app.services.ics import build_feed


def _sched(entry_id, routine_type, day):
    return SimpleNamespace(id=entry_id, routine_type=routine_type, scheduled_date=day)


# ── Builder ────────────────────────────────────────────────────────


def test_feed_skeleton_and_events():
    feed = build_feed(
        [_sched(1, 'gym', date(2026, 7, 10)), _sched(2, 'bwf', date(2026, 7, 12))],
        {'gym': 'Gym', 'bwf': 'BWF'},
    )
    assert feed.startswith('BEGIN:VCALENDAR\r\n')
    assert feed.endswith('END:VCALENDAR\r\n')
    assert feed.count('BEGIN:VEVENT') == 2
    assert 'UID:nofluff-sched-1@nofluff' in feed
    assert 'DTSTART;VALUE=DATE:20260710' in feed
    assert 'DTEND;VALUE=DATE:20260711' in feed  # all-day: exclusive end
    assert 'SUMMARY:Workout: Gym' in feed
    assert 'BEGIN:VALARM' in feed
    # CRLF-only line endings
    assert '\n' not in feed.replace('\r\n', '')


def test_feed_escapes_labels():
    feed = build_feed([_sched(1, 'ai-1', date(2026, 7, 10))], {'ai-1': 'Legs; heavy, maybe\\'})
    assert 'SUMMARY:Workout: Legs\\; heavy\\, maybe\\\\' in feed


def test_feed_folds_long_lines_under_75_octets():
    long_label = 'Climbing power endurance block — semaine três longue ' * 3
    feed = build_feed([_sched(1, 'ai-2', date(2026, 7, 10))], {'ai-2': long_label})
    for line in feed.split('\r\n'):
        assert len(line.encode()) <= 75
    assert '\r\n ' in feed  # a folded continuation exists
    assert 'Climbing power endurance block' in feed.replace('\r\n ', '')


# ── Route + token lifecycle ────────────────────────────────────────


def _enable_feed(client):
    return client.post('/schedule/calendar_feed', data={'action': 'enable'})


def _token(app):
    with app.app_context():
        return User.query.first().ics_token


def test_feed_route_serves_user_schedule(logged_in_client, app):
    client = logged_in_client
    client.post('/schedule/plan', json={'date': date.today().isoformat(), 'routine_type': 'gym'})
    _enable_feed(client)

    resp = client.get(f'/calendar/feed/{_token(app)}.ics')
    assert resp.status_code == 200
    assert resp.mimetype == 'text/calendar'
    assert b'SUMMARY:Workout: Gym' in resp.data


def test_unknown_token_is_404(client):
    assert client.get('/calendar/feed/not-a-token.ics').status_code == 404


def test_regenerate_invalidates_the_old_link(logged_in_client, app):
    client = logged_in_client
    _enable_feed(client)
    old = _token(app)

    client.post('/schedule/calendar_feed', data={'action': 'regenerate'})
    new = _token(app)

    assert old != new
    assert client.get(f'/calendar/feed/{old}.ics').status_code == 404
    assert client.get(f'/calendar/feed/{new}.ics').status_code == 200


def test_disable_removes_the_feed(logged_in_client, app):
    client = logged_in_client
    _enable_feed(client)
    token = _token(app)

    client.post('/schedule/calendar_feed', data={'action': 'disable'})

    assert _token(app) is None
    assert client.get(f'/calendar/feed/{token}.ics').status_code == 404


def test_schedule_page_shows_feed_controls(logged_in_client):
    client = logged_in_client
    assert b'Enable calendar feed' in client.get('/schedule').data
    _enable_feed(client)
    resp = client.get('/schedule')
    assert b'/calendar/feed/' in resp.data
    assert b'Regenerate link' in resp.data
