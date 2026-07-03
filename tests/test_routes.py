from app.models import ExerciseLog, User, Workout


def test_home_shows_bwf_routine(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'Warm-up' in resp.data


def test_home_shows_gym_routine(client):
    resp = client.get('/?routine=gym')
    assert resp.status_code == 200
    assert b'Bench Press' in resp.data


def test_register_rejects_short_password(client):
    resp = client.post(
        '/register',
        data={
            'username': 'shorty',
            'email': 'shorty@example.com',
            'password': 'short',
        },
        follow_redirects=True,
    )
    assert b'at least 8 characters' in resp.data


def test_register_and_login(logged_in_client, app):
    with app.app_context():
        user = User.query.filter_by(username='testuser').first()
        assert user is not None
        assert user.progressions.count() > 0


def test_full_gym_workout_flow(logged_in_client, app):
    client = logged_in_client

    resp = client.get('/start_workout?routine_type=gym', follow_redirects=True)
    assert b'Workout started' in resp.data

    resp = client.post(
        '/log_exercise/Bench Press',
        data={
            'routine': 'gym',
            'section': 'Push',
            'index': '0',
            'weight_unit': 'lbs',
            'weight_set_1': '95',
            'reps_set_1': '10',
            'weight_set_2': '95',
            'reps_set_2': '8',
            'weight_set_3': '90',
            'reps_set_3': '6',
        },
        follow_redirects=True,
    )
    assert b'Exercise logged' in resp.data

    with app.app_context():
        log = ExerciseLog.query.filter_by(exercise_name='Bench Press').first()
        assert log is not None
        assert log.sets_completed == 3
        assert log.get_weights_list() == [95.0, 95.0, 90.0]
        assert log.get_reps_list() == [10, 8, 6]
        assert log.weight_unit == 'lbs'
        assert log.workout.routine_type == 'gym'

    resp = client.get('/end_workout', follow_redirects=True)
    assert b'Workout completed' in resp.data


def test_empty_workout_is_cancelled(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=bwf')
    resp = client.get('/end_workout', follow_redirects=True)
    assert b'Workout cancelled' in resp.data
    with app.app_context():
        assert Workout.query.count() == 0


def test_log_exercise_requires_active_workout(logged_in_client):
    resp = logged_in_client.post(
        '/log_exercise/Bench Press',
        data={
            'routine': 'gym',
            'section': 'Push',
            'index': '0',
            'weight_set_1': '95',
            'reps_set_1': '10',
        },
        follow_redirects=True,
    )
    assert b'No active workout' in resp.data


def test_workout_detail_blocked_for_other_users(logged_in_client, app):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    client.post(
        '/log_exercise/Bench Press',
        data={
            'routine': 'gym',
            'section': 'Push',
            'index': '0',
            'weight_set_1': '95',
            'reps_set_1': '10',
        },
    )
    client.get('/end_workout')

    with app.app_context():
        workout_id = Workout.query.first().id

    client.get('/logout')
    client.post(
        '/register',
        data={
            'username': 'intruder',
            'email': 'intruder@example.com',
            'password': 'intruderpass1',
        },
    )
    client.post('/login', data={'username': 'intruder', 'password': 'intruderpass1'})

    resp = client.get(f'/workout/{workout_id}', follow_redirects=True)
    assert b'do not have permission' in resp.data


def test_home_page_prefills_last_gym_log(logged_in_client):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    client.post(
        '/log_exercise/Bench Press',
        data={
            'routine': 'gym',
            'section': 'Push',
            'index': '0',
            'weight_unit': 'lbs',
            'weight_set_1': '105',
            'reps_set_1': '9',
        },
    )

    resp = client.get('/?routine=gym')
    assert resp.status_code == 200
    assert b'Last session' in resp.data
    assert b'105' in resp.data


def test_home_defaults_to_last_used_routine(logged_in_client):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')
    client.get('/end_workout')

    resp = client.get('/')  # no ?routine param
    assert b'Bench Press' in resp.data


def test_add_and_remove_custom_exercise(logged_in_client):
    client = logged_in_client

    resp = client.post(
        '/routine/add_exercise',
        data={
            'section': 'Push',
            'name': 'Incline Press',
            'sets': '4',
            'reps': '8-10',
            'equipment': 'dumbbell',
        },
        follow_redirects=True,
    )
    assert b'Incline Press' in resp.data
    assert b'custom' in resp.data

    resp = client.post(
        '/routine/add_exercise',
        data={
            'section': 'Push',
            'name': 'Incline Press',
            'equipment': 'dumbbell',
        },
        follow_redirects=True,
    )
    assert b'already in your routine' in resp.data

    client.post('/routine/remove_exercise', data={'name': 'Incline Press'})
    client.get('/?routine=gym')  # consume the "Removed ..." flash
    resp = client.get('/?routine=gym')
    assert b'Incline Press' not in resp.data


def test_hide_and_restore_default_exercise(logged_in_client):
    client = logged_in_client

    client.post('/routine/remove_exercise', data={'name': 'Leg Curl'})
    client.get('/?routine=gym')  # consume the "Removed ..." flash
    resp = client.get('/?routine=gym')
    assert b'Leg Curl' not in resp.data

    client.post('/routine/restore_exercises', data={})
    resp = client.get('/?routine=gym')
    assert b'Leg Curl' in resp.data


def test_weight_picker_on_all_weighted_exercises(logged_in_client):
    client = logged_in_client
    client.get('/start_workout?routine_type=gym')

    resp = client.get('/?routine=gym')
    assert resp.status_code == 200
    # 10 weighted exercises (all gym exercises except Crunches) get a picker
    assert resp.data.count(b'weight-picker') == 10
    # Equipment defaults are encoded in data attributes
    assert b'data-default-equipment="barbell"' in resp.data
    assert b'data-default-equipment="dumbbell"' in resp.data
    assert b'data-default-equipment="machine"' in resp.data
