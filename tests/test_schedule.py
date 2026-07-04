"""Scheduling, rotation, planning, and a few other under-tested routes."""

from datetime import date

from app import create_app, db
from app.models import ExerciseLog, RotationEntry, User, Workout, WorkoutSchedule
from config import Config


class CsrfConfig(Config):
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    TESTING = True
    WTF_CSRF_ENABLED = True
    RATELIMIT_ENABLED = False
    ANTHROPIC_API_KEY = None


def _user(username='testuser'):
    return User.query.filter_by(username=username).first()


# ── schedule page + rotation ────────────────────────────────────────


def test_schedule_page_renders(logged_in_client):
    resp = logged_in_client.get('/schedule')
    assert resp.status_code == 200
    assert b'BWF' in resp.data
    assert b'Gym' in resp.data


def test_save_rotation_persists_valid_entries(app, logged_in_client):
    resp = logged_in_client.post('/schedule/rotation', json={'rotation': ['gym', 'bwf', 'bogus']})
    assert resp.status_code == 200
    with app.app_context():
        entries = (
            RotationEntry.query.filter_by(user_id=_user().id).order_by(RotationEntry.position).all()
        )
        # 'bogus' is not a valid routine key and is dropped.
        assert [e.routine_type for e in entries] == ['gym', 'bwf']


# ── plan / unplan ───────────────────────────────────────────────────


def test_plan_workout_creates_then_updates_same_date(app, logged_in_client):
    r1 = logged_in_client.post('/schedule/plan', json={'date': '2030-06-01', 'routine_type': 'gym'})
    assert r1.status_code == 200
    r2 = logged_in_client.post('/schedule/plan', json={'date': '2030-06-01', 'routine_type': 'bwf'})
    assert r2.status_code == 200
    with app.app_context():
        entries = WorkoutSchedule.query.filter_by(user_id=_user().id).all()
        # Unique (user, date) — the second plan updates in place.
        assert len(entries) == 1
        assert entries[0].routine_type == 'bwf'


def test_plan_workout_rejects_invalid_routine(logged_in_client):
    resp = logged_in_client.post('/schedule/plan', json={'date': '2030-06-01', 'routine_type': 'x'})
    assert resp.status_code == 400


def test_unplan_workout_only_deletes_own(app, logged_in_client):
    with app.app_context():
        other = User(username='other', email='o@example.com', password_hash='x')
        db.session.add(other)
        db.session.commit()
        mine = WorkoutSchedule(
            user_id=_user().id, routine_type='gym', scheduled_date=date(2030, 6, 2)
        )
        theirs = WorkoutSchedule(
            user_id=other.id, routine_type='gym', scheduled_date=date(2030, 6, 2)
        )
        db.session.add_all([mine, theirs])
        db.session.commit()
        mine_id, theirs_id = mine.id, theirs.id

    logged_in_client.delete(f'/schedule/plan/{theirs_id}')
    logged_in_client.delete(f'/schedule/plan/{mine_id}')

    with app.app_context():
        assert db.session.get(WorkoutSchedule, theirs_id) is not None  # not ours — untouched
        assert db.session.get(WorkoutSchedule, mine_id) is None


# ── today's plan on the home page ───────────────────────────────────


def test_home_surfaces_scheduled_today(app, logged_in_client):
    with app.app_context():
        db.session.add(
            WorkoutSchedule(user_id=_user().id, routine_type='gym', scheduled_date=date.today())
        )
        db.session.commit()
    resp = logged_in_client.get('/')
    assert resp.status_code == 200
    assert b'Scheduled' in resp.data


# ── logout + exercise detail ────────────────────────────────────────


def test_logout_ends_session(logged_in_client):
    assert logged_in_client.get('/logout').status_code == 302
    after = logged_in_client.get('/dashboard')
    assert after.status_code == 302
    assert '/login' in after.headers['Location']


def test_exercise_detail_renders(app, logged_in_client):
    with app.app_context():
        gym_section = next(iter(app.config['GYM_ROUTINE_DATA']))
        bwf_section = next(iter(app.config['ROUTINE_DATA']))
    assert logged_in_client.get(f'/exercise/{gym_section}/0?routine=gym').status_code == 200
    assert logged_in_client.get(f'/exercise/{bwf_section}/0?routine=bwf').status_code == 200


def test_workout_detail_shows_progression_name(app, logged_in_client):
    with app.app_context():
        workout = Workout(user_id=_user().id, routine_type='bwf')
        db.session.add(workout)
        db.session.commit()
        db.session.add(
            ExerciseLog(
                workout_id=workout.id,
                exercise_name='Pull-up Progression',
                sets_completed=3,
                reps_per_set='8,8,8',
                progression_level=1,
            )
        )
        db.session.commit()
        workout_id = workout.id

    resp = logged_in_client.get(f'/workout/{workout_id}')
    assert resp.status_code == 200
    assert b'Scapular Pulls' in resp.data  # level-1 name for the progression


# ── CSRF protection on JSON endpoints ───────────────────────────────


def test_json_endpoint_requires_csrf_token_when_enabled():
    app = create_app(CsrfConfig)
    with app.app_context():
        db.create_all()
        user = User(username='csrf', email='csrf@example.com', password_hash='x')
        db.session.add(user)
        db.session.commit()
        uid = user.id
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
    resp = client.post('/schedule/plan', json={'date': '2030-01-01', 'routine_type': 'gym'})
    assert resp.status_code == 400
    with app.app_context():
        db.drop_all()
