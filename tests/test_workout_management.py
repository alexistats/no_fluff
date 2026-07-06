"""Phase 1: deleting workouts and per-exercise notes."""

from app import db
from app.models import ExerciseLog, Workout


def _log_bench_press(client, notes=None):
    data = {
        'routine': 'gym',
        'section': 'Push',
        'index': '0',
        'weight_unit': 'lbs',
        'weight_set_1': '95',
        'reps_set_1': '10',
    }
    if notes is not None:
        data['notes'] = notes
    return client.post('/log_exercise/Bench Press', data=data, follow_redirects=True)


def _only_workout_id(app):
    with app.app_context():
        return Workout.query.one().id


# ── Deleting workouts ──────────────────────────────────────────────


def test_delete_workout_removes_its_logs(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    _log_bench_press(client)
    client.get('/end_workout')
    workout_id = _only_workout_id(app)

    resp = client.post(f'/workout/{workout_id}/delete', follow_redirects=True)

    assert b'Workout deleted' in resp.data
    with app.app_context():
        assert Workout.query.count() == 0
        assert ExerciseLog.query.count() == 0


def test_delete_requires_login(client):
    resp = client.post('/workout/1/delete')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_cannot_delete_another_users_workout(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    _log_bench_press(client)
    client.get('/end_workout')
    workout_id = _only_workout_id(app)

    client.get('/logout')
    client.post(
        '/register',
        data={'username': 'other', 'email': 'other@example.com', 'password': 'password1234'},
    )
    client.post('/login', data={'username': 'other', 'password': 'password1234'})

    resp = client.post(f'/workout/{workout_id}/delete', follow_redirects=True)

    assert b'Workout not found' in resp.data
    with app.app_context():
        assert Workout.query.count() == 1


def test_deleting_active_workout_ends_the_session(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    _log_bench_press(client)
    workout_id = _only_workout_id(app)

    client.post(f'/workout/{workout_id}/delete')

    resp = _log_bench_press(client)
    assert b'No active workout' in resp.data


def test_dashboard_and_detail_show_delete_controls(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    _log_bench_press(client)
    client.get('/end_workout')
    workout_id = _only_workout_id(app)

    assert f'/workout/{workout_id}/delete'.encode() in client.get('/dashboard').data
    assert f'/workout/{workout_id}/delete'.encode() in client.get(f'/workout/{workout_id}').data


# ── Per-exercise notes ─────────────────────────────────────────────


def test_gym_log_stores_note_and_detail_shows_it(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    _log_bench_press(client, notes='Felt heavy, slow eccentric')
    workout_id = _only_workout_id(app)

    with app.app_context():
        assert ExerciseLog.query.one().notes == 'Felt heavy, slow eccentric'
    assert b'Felt heavy, slow eccentric' in client.get(f'/workout/{workout_id}').data


def test_bwf_log_stores_note(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=bwf')
    client.post(
        '/log_exercise/Pull-up Progression',
        data={
            'routine': 'bwf',
            'section': 'Pull-up',
            'index': '0',
            'progression_level': '1',
            'reps_set_1': '5',
            'reps_set_2': '5',
            'notes': '  used the thick bar  ',
        },
    )
    with app.app_context():
        assert ExerciseLog.query.one().notes == 'used the thick bar'


def test_note_is_truncated_to_500_chars(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    _log_bench_press(client, notes='x' * 800)
    with app.app_context():
        assert len(ExerciseLog.query.one().notes) == 500


def test_home_shows_note_indicator_for_last_session(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    _log_bench_press(client, notes='rack was busy')
    client.get('/end_workout')

    resp = client.get('/?routine=gym')
    assert b'rack was busy' in resp.data

    with app.app_context():
        db.session.query(ExerciseLog).delete()
        db.session.commit()
    resp = client.get('/?routine=gym')
    assert b'rack was busy' not in resp.data
