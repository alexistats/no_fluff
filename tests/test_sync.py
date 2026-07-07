"""Phase 5: the offline-sync batch endpoint."""

import uuid

from app.models import ExerciseLog, UserProgression, Workout


def _sync(client, payload):
    return client.post(
        '/sync/workout', json=payload, headers={'X-Requested-With': 'XMLHttpRequest'}
    )


def _batch(client_uuid, logs, routine='gym', **extra):
    payload = {
        'client_uuid': client_uuid,
        'routine_type': routine,
        'started_at': '2026-07-05T18:30:00Z',
        'logs': logs,
    }
    payload.update(extra)
    return payload


def _log(name='Bench Press', reps=('10', '8'), weights=('95', '95'), **extra):
    entry = {
        'client_log_id': str(uuid.uuid4()),
        'exercise_name': name,
        'section': 'Push',
        'reps': list(reps),
        'weights': list(weights),
        'weight_unit': 'lbs',
        'progression_level': None,
        'notes': '',
        'logged_at': '2026-07-05T18:45:00Z',
    }
    entry.update(extra)
    return entry


# ── Guards ─────────────────────────────────────────────────────────


def test_requires_ajax_header(logged_in_client):
    resp = logged_in_client.post('/sync/workout', json={})
    assert resp.status_code == 403


def test_unauthenticated_gets_401(client):
    resp = client.post('/sync/workout', json={}, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 401


def test_needs_a_workout_reference(logged_in_client):
    assert _sync(logged_in_client, {'logs': []}).status_code == 400


def test_new_offline_workout_needs_valid_routine(logged_in_client):
    payload = _batch(str(uuid.uuid4()), [], routine='not-a-routine')
    assert _sync(logged_in_client, payload).status_code == 400


# ── Creating and replaying batches ─────────────────────────────────


def test_batch_creates_workout_and_logs(logged_in_client, app):
    cid = str(uuid.uuid4())
    resp = _sync(logged_in_client, _batch(cid, [_log(), _log(name='Incline Press')]))

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['accepted']) == 2

    with app.app_context():
        workout = Workout.query.one()
        assert workout.client_uuid == cid
        assert workout.routine_type == 'gym'
        assert workout.exercises.count() == 2
        log = ExerciseLog.query.filter_by(exercise_name='Bench Press').one()
        assert log.reps_per_set == '10,8'
        assert log.weight_per_set == '95,95'


def test_replaying_the_same_batch_is_idempotent(logged_in_client, app):
    cid = str(uuid.uuid4())
    batch = _batch(cid, [_log()])

    first = _sync(logged_in_client, batch).get_json()
    second = _sync(logged_in_client, batch).get_json()

    assert first['workout_id'] == second['workout_id']
    assert first['accepted'] == second['accepted']  # acknowledged again, not re-added
    with app.app_context():
        assert Workout.query.count() == 1
        assert ExerciseLog.query.count() == 1


def test_partial_replay_inserts_only_new_logs(logged_in_client, app):
    cid = str(uuid.uuid4())
    known = _log()
    _sync(logged_in_client, _batch(cid, [known]))

    resp = _sync(logged_in_client, _batch(cid, [known, _log(name='Row')]))

    assert len(resp.get_json()['accepted']) == 2
    with app.app_context():
        assert ExerciseLog.query.count() == 2


def test_logs_attach_to_an_existing_online_workout(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    with app.app_context():
        workout_id = Workout.query.one().id

    resp = _sync(client, {'workout_id': workout_id, 'logs': [_log()]})

    assert resp.status_code == 200
    with app.app_context():
        assert Workout.query.count() == 1  # no duplicate workout created
        assert ExerciseLog.query.one().workout_id == workout_id


def test_cannot_sync_into_someone_elses_workout(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    with app.app_context():
        workout_id = Workout.query.one().id

    client.get('/logout')
    client.post(
        '/register',
        data={'username': 'other', 'email': 'other@example.com', 'password': 'password1234'},
    )
    client.post('/login', data={'username': 'other', 'password': 'password1234'})

    resp = _sync(client, {'workout_id': workout_id, 'logs': [_log()]})
    assert resp.status_code == 404


def test_bwf_sync_advances_progressions(logged_in_client, app):
    entry = _log(name='Pull-up Progression', reps=('8', '8', '8'), weights=(), progression_level=1)
    resp = _sync(logged_in_client, _batch(str(uuid.uuid4()), [entry], routine='bwf'))

    assert resp.status_code == 200
    with app.app_context():
        progression = UserProgression.query.filter_by(exercise_category='Pull-up Progression').one()
        assert progression.current_progression == 2


def test_garbage_logs_are_skipped_not_fatal(logged_in_client, app):
    cid = str(uuid.uuid4())
    logs = [
        'not-a-dict',
        {'client_log_id': ''},  # no id
        {'client_log_id': str(uuid.uuid4()), 'exercise_name': '', 'reps': ['5']},  # no name
        {'client_log_id': str(uuid.uuid4()), 'exercise_name': 'Row', 'reps': []},  # no reps
        _log(),
    ]
    resp = _sync(logged_in_client, _batch(cid, logs))

    assert resp.status_code == 200
    assert len(resp.get_json()['accepted']) == 1
    with app.app_context():
        assert ExerciseLog.query.count() == 1
