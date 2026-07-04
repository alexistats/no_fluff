"""Dashboard aggregation — harness that pins output across the Phase 4 refactor."""

import json
import re
from datetime import UTC, date, datetime, timedelta

from app import db
from app.models import ExerciseLog, User, Workout
from app.services import stats


def _dashboard_data(html):
    """Parse the #dashboard-data JSON block the charts read from."""
    match = re.search(r'id="dashboard-data"[^>]*>(.*?)</script>', html, re.S)
    assert match, 'dashboard-data block not found'
    return json.loads(match.group(1))


def _seed(app):
    with app.app_context():
        user = User.query.filter_by(username='testuser').first()
        now = datetime.now(UTC)
        gym1 = Workout(user_id=user.id, routine_type='gym')  # date defaults to now
        gym2 = Workout(user_id=user.id, routine_type='gym')
        old = Workout(user_id=user.id, routine_type='bwf', date=now - timedelta(days=400))
        db.session.add_all([gym1, gym2, old])
        db.session.commit()
        db.session.add(
            ExerciseLog(
                workout_id=gym1.id,
                exercise_name='Bench Press',
                sets_completed=1,
                reps_per_set='5',
                weight_per_set='100,100',
                weight_unit='lbs',
            )
        )
        db.session.commit()


def test_dashboard_aggregates(app, logged_in_client):
    _seed(app)
    resp = logged_in_client.get('/dashboard')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Totals: 3 all-time; the two "now" workouts fall in this week and month,
    # the 400-day-old one does not.
    assert '<span class="dash-stat-num">3</span>' in html
    assert html.count('<span class="dash-stat-num">2</span>') >= 2

    data = _dashboard_data(html)
    assert data['routine_breakdown'] == [
        {'label': 'Gym', 'count': 2},
        {'label': 'BWF', 'count': 1},
    ]
    assert data['top_exercises'] == [{'name': 'Bench Press', 'count': 1}]
    assert list(data['weight_trends'].keys()) == ['Bench Press']
    assert data['weight_trends']['Bench Press'][0]['weight'] == 45.4  # 100 lbs -> kg


def test_dashboard_empty_state(logged_in_client):
    resp = logged_in_client.get('/dashboard')
    assert resp.status_code == 200
    assert '<span class="dash-stat-num">0</span>' in resp.get_data(as_text=True)


# ── stats unit tests: exact week/month boundary behaviour ───────────


def _make_user(username='statsuser'):
    user = User(username=username, email=f'{username}@example.com', password_hash='x')
    db.session.add(user)
    db.session.commit()
    return user


def test_workout_counts_boundaries(app):
    with app.app_context():
        user = _make_user()
        today = date(2026, 6, 15)
        db.session.add_all(
            [
                Workout(user_id=user.id, date=datetime(2026, 6, 15, tzinfo=UTC)),  # week + month
                Workout(user_id=user.id, date=datetime(2026, 6, 1, tzinfo=UTC)),  # month only
                Workout(user_id=user.id, date=datetime(2026, 5, 15, tzinfo=UTC)),  # neither
            ]
        )
        db.session.commit()
        assert stats.workout_counts(user.id, today) == {
            'total': 3,
            'this_week': 1,
            'this_month': 2,
        }


def test_weekly_frequency_buckets_by_iso_week(app):
    with app.app_context():
        user = _make_user()
        today = date(2026, 6, 15)
        db.session.add_all(
            [
                Workout(user_id=user.id, date=datetime(2026, 6, 15, tzinfo=UTC)),  # current week
                Workout(user_id=user.id, date=datetime(2026, 6, 8, tzinfo=UTC)),  # week before
                Workout(user_id=user.id, date=datetime(2025, 1, 1, tzinfo=UTC)),  # outside window
            ]
        )
        db.session.commit()
        labels, values = stats.weekly_frequency(user.id, today, weeks=12)
        assert len(labels) == len(values) == 12
        assert sum(values) == 2  # the 2025 workout is outside the 12-week window
        assert values[-1] == 1  # current week
        assert values[-2] == 1  # previous week
