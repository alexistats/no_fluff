import json

import pytest

from app import ai_generator, db
from app.models import (
    CustomExercise,
    ExerciseLog,
    GeneratedProgram,
    HiddenExercise,
    UserApiKey,
    Workout,
)

SAMPLE_ROUTINE = {
    'Day 1 – Pull & Core': [
        {
            'name': 'Band Pull-aparts',
            'sets': '2',
            'reps': '15',
            'weighted': False,
            'equipment': 'bodyweight',
            'description': 'Warm up the shoulders.',
        },
        {
            'name': 'Weighted Pull-ups',
            'sets': '3',
            'reps': '5-8',
            'weighted': True,
            'equipment': 'bodyweight',
            'description': 'Full range of motion.',
        },
        {
            'name': 'Dumbbell Row',
            'sets': '3',
            'reps': '8-12',
            'weighted': True,
            'equipment': 'dumbbell',
            'description': 'Keep a flat back.',
        },
    ],
}


def _fake_generate(api_key, inputs, previous_program=None, feedback=None):
    return 'Climbing Strength', 'A pull-focused program.', SAMPLE_ROUTINE


def _generate_form(**overrides):
    form = {
        'goal': 'climbing',
        'equipment': ['pull-up bar', 'dumbbells'],
        'days_per_week': '3',
        'session_length': '60',
        'experience': 'intermediate',
        'notes': '',
    }
    form.update(overrides)
    return form


def _create_program(app, is_draft=False, user_id=None):
    with app.app_context():
        if user_id is None:
            from app.models import User

            user_id = User.query.filter_by(username='testuser').first().id
        program = GeneratedProgram(
            user_id=user_id,
            name='Climbing Strength',
            goal='climbing',
            description='A pull-focused program.',
            program_json=json.dumps(SAMPLE_ROUTINE),
            inputs_json=json.dumps(_generate_form()),
            is_draft=is_draft,
        )
        db.session.add(program)
        db.session.commit()
        return program.id


# ── validate_program ────────────────────────────────────────────────


def _model_output(sections=None):
    return {
        'program_name': 'Climbing Strength',
        'description': 'A pull-focused program.',
        'sections': sections
        if sections is not None
        else [
            {
                'name': 'Day 1 – Pull & Core',
                'exercises': list(SAMPLE_ROUTINE['Day 1 – Pull & Core']),
            },
        ],
    }


def test_validate_program_accepts_valid_output():
    name, description, routine = ai_generator.validate_program(_model_output())
    assert name == 'Climbing Strength'
    assert description == 'A pull-focused program.'
    assert list(routine) == ['Day 1 – Pull & Core']
    assert routine['Day 1 – Pull & Core'][2]['equipment'] == 'dumbbell'


def test_validate_program_rejects_duplicate_exercise_names():
    data = _model_output()
    dup = dict(data['sections'][0]['exercises'][1], name='Dumbbell Row')
    data['sections'][0]['exercises'][1] = dup
    with pytest.raises(ValueError):
        ai_generator.validate_program(data)


def test_validate_program_rejects_bad_equipment():
    data = _model_output()
    data['sections'][0]['exercises'][0]['equipment'] = 'trampoline'
    with pytest.raises(ValueError):
        ai_generator.validate_program(data)


def test_validate_program_rejects_sets_out_of_range():
    data = _model_output()
    data['sections'][0]['exercises'][0]['sets'] = '9'
    with pytest.raises(ValueError):
        ai_generator.validate_program(data)


def test_validate_program_rejects_too_many_sections():
    section = _model_output()['sections'][0]
    sections = [
        {'name': f'Day {i}', 'exercises': [dict(section['exercises'][0], name=f'Exercise {i}')]}
        for i in range(ai_generator.MAX_SECTIONS + 1)
    ]
    with pytest.raises(ValueError):
        ai_generator.validate_program(_model_output(sections))


# ── generation flow ─────────────────────────────────────────────────


def test_generate_requires_login(client):
    response = client.get('/generate')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_generate_without_any_key_redirects_to_settings(logged_in_client):
    response = logged_in_client.post('/generate', data=_generate_form())
    assert '/settings' in response.headers['Location']


def test_generate_creates_draft_and_preview(app, logged_in_client, monkeypatch):
    app.config['ANTHROPIC_API_KEY'] = 'server-key'
    monkeypatch.setattr(ai_generator, 'generate_program', _fake_generate)

    response = logged_in_client.post('/generate', data=_generate_form())
    assert response.status_code == 302
    assert '/generate/preview/' in response.headers['Location']

    with app.app_context():
        program = GeneratedProgram.query.one()
        assert program.is_draft
        assert program.name == 'Climbing Strength'
        assert 'Dumbbell Row' in program.program_json
        program_id = program.id

    page = logged_in_client.get(f'/generate/preview/{program_id}')
    assert page.status_code == 200
    assert b'Climbing Strength' in page.data
    assert b'Dumbbell Row' in page.data


def test_generation_error_flashes_and_creates_nothing(app, logged_in_client, monkeypatch):
    app.config['ANTHROPIC_API_KEY'] = 'server-key'

    def boom(api_key, inputs, previous_program=None, feedback=None):
        raise ai_generator.GenerationError('The Claude API key was rejected.')

    monkeypatch.setattr(ai_generator, 'generate_program', boom)
    response = logged_in_client.post('/generate', data=_generate_form(), follow_redirects=True)
    assert b'rejected' in response.data
    with app.app_context():
        assert GeneratedProgram.query.count() == 0


def test_accept_program_saves_and_shows_on_home(app, logged_in_client):
    program_id = _create_program(app, is_draft=True)

    response = logged_in_client.post(f'/generate/accept/{program_id}')
    assert response.headers['Location'].endswith(f'/?routine=ai-{program_id}')

    with app.app_context():
        assert GeneratedProgram.query.get(program_id).is_draft is False

    page = logged_in_client.get(f'/?routine=ai-{program_id}')
    assert b'Climbing Strength' in page.data
    assert b'Weighted Pull-ups' in page.data


def test_retry_passes_feedback_and_overwrites_draft(app, logged_in_client, monkeypatch):
    app.config['ANTHROPIC_API_KEY'] = 'server-key'
    program_id = _create_program(app, is_draft=True)
    captured = {}

    def fake_retry(api_key, inputs, previous_program=None, feedback=None):
        captured['previous'] = previous_program
        captured['feedback'] = feedback
        return 'Climbing Strength v2', 'Revised.', SAMPLE_ROUTINE

    monkeypatch.setattr(ai_generator, 'generate_program', fake_retry)
    logged_in_client.post(f'/generate/retry/{program_id}', data={'feedback': 'less volume'})

    assert captured['feedback'] == 'less volume'
    assert 'Day 1 – Pull & Core' in captured['previous']
    with app.app_context():
        program = GeneratedProgram.query.get(program_id)
        assert program.name == 'Climbing Strength v2'


def test_other_users_program_is_not_accessible(app, client):
    client.post(
        '/register',
        data={'username': 'testuser', 'email': 'test@example.com', 'password': 'testpassword123'},
    )
    program_id = _create_program(app, is_draft=False)

    client.post(
        '/register',
        data={
            'username': 'intruder',
            'email': 'intruder@example.com',
            'password': 'testpassword123',
        },
    )
    client.post('/login', data={'username': 'intruder', 'password': 'testpassword123'})

    page = client.get(f'/generate/preview/{program_id}', follow_redirects=True)
    assert b'Program not found.' in page.data
    # Home falls back to bwf instead of rendering someone else's program
    page = client.get(f'/?routine=ai-{program_id}')
    assert b'Climbing Strength' not in page.data


def test_log_exercise_against_ai_routine(app, logged_in_client):
    program_id = _create_program(app, is_draft=False)
    routine_key = f'ai-{program_id}'

    logged_in_client.get(f'/start_workout?routine_type={routine_key}')
    response = logged_in_client.post(
        '/log_exercise/Dumbbell Row',
        data={
            'routine': routine_key,
            'section': 'Day 1 – Pull & Core',
            'index': '2',
            'reps_set_1': '10',
            'weight_set_1': '50',
            'reps_set_2': '9',
            'weight_set_2': '50',
            'weight_unit': 'lbs',
        },
    )
    assert response.status_code == 302

    with app.app_context():
        log = ExerciseLog.query.filter_by(exercise_name='Dumbbell Row').one()
        assert log.reps_per_set == '10,9'
        assert log.weight_per_set == '50,50'
        assert Workout.query.get(log.workout_id).routine_type == routine_key


def test_customize_ai_routine(app, logged_in_client):
    program_id = _create_program(app, is_draft=False)
    routine_key = f'ai-{program_id}'

    logged_in_client.post(
        '/routine/add_exercise',
        data={
            'routine': routine_key,
            'section': 'Day 1 – Pull & Core',
            'name': 'Face Pulls',
            'sets': '3',
            'reps': '12-15',
            'equipment': 'machine',
        },
    )
    # follow_redirects consumes the 'Removed "..."' flash so it can't
    # mask the assertion on the next page load
    logged_in_client.post(
        '/routine/remove_exercise',
        data={
            'routine': routine_key,
            'name': 'Band Pull-aparts',
        },
        follow_redirects=True,
    )

    with app.app_context():
        assert CustomExercise.query.filter_by(routine_type=routine_key).count() == 1
        assert HiddenExercise.query.filter_by(routine_type=routine_key).count() == 1

    page = logged_in_client.get(f'/?routine={routine_key}')
    assert b'Face Pulls' in page.data
    assert b'Band Pull-aparts' not in page.data


def test_delete_program_removes_overlays(app, logged_in_client):
    program_id = _create_program(app, is_draft=False)
    routine_key = f'ai-{program_id}'
    logged_in_client.post(
        '/routine/remove_exercise', data={'routine': routine_key, 'name': 'Band Pull-aparts'}
    )

    logged_in_client.post(f'/program/delete/{program_id}')

    with app.app_context():
        assert GeneratedProgram.query.count() == 0
        assert HiddenExercise.query.filter_by(routine_type=routine_key).count() == 0


# ── settings / API key storage ──────────────────────────────────────


def test_settings_stores_key_encrypted(app, logged_in_client):
    logged_in_client.post('/settings', data={'api_key': 'sk-ant-test-1234'})

    with app.app_context():
        record = UserApiKey.query.one()
        assert 'sk-ant-test-1234' not in record.encrypted_key
        assert record.get_key() == 'sk-ant-test-1234'
        assert record.key_hint() == '1234'

    page = logged_in_client.get('/settings')
    assert b'1234' in page.data
    assert b'sk-ant-test-1234' not in page.data

    logged_in_client.post('/settings', data={'action': 'clear'})
    with app.app_context():
        assert UserApiKey.query.count() == 0


def test_user_key_overrides_server_key(app, logged_in_client):
    app.config['ANTHROPIC_API_KEY'] = 'server-key'
    logged_in_client.post('/settings', data={'api_key': 'user-key'})

    with app.app_context():
        from app.models import User

        user = User.query.filter_by(username='testuser').first()
        assert ai_generator.resolve_api_key(user) == 'user-key'


# ── generate_program transport handling (stubs _get_completion) ──────


class _FakeBlock:
    type = 'text'

    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, stop_reason, text=''):
        self.stop_reason = stop_reason
        self.content = [_FakeBlock(text)] if text else []


_INPUTS = {
    'goal': 'strength',
    'equipment': ['barbell'],
    'days_per_week': 3,
    'session_length': 60,
    'experience': 'beginner',
    'notes': '',
}


def test_generate_program_reports_truncation(app, monkeypatch):
    monkeypatch.setattr(
        ai_generator, '_get_completion', lambda client, messages: _FakeMessage('max_tokens', '{}')
    )
    with app.app_context(), pytest.raises(ai_generator.GenerationError, match='too long'):
        ai_generator.generate_program('sk-test', _INPUTS)


def test_generate_program_reports_refusal(app, monkeypatch):
    monkeypatch.setattr(
        ai_generator, '_get_completion', lambda client, messages: _FakeMessage('refusal')
    )
    with app.app_context(), pytest.raises(ai_generator.GenerationError, match='declined'):
        ai_generator.generate_program('sk-test', _INPUTS)


def test_generate_program_retries_with_correction(app, monkeypatch):
    calls = []

    def fake(client, messages):
        calls.append([m['role'] for m in messages])
        return _FakeMessage('end_turn', 'not valid json')

    monkeypatch.setattr(ai_generator, '_get_completion', fake)
    with app.app_context(), pytest.raises(ai_generator.GenerationError, match='invalid program'):
        ai_generator.generate_program('sk-test', _INPUTS)

    assert len(calls) == 2
    # The retry feeds back the rejected answer plus a correction turn.
    assert calls[0] == ['user']
    assert calls[1] == ['user', 'assistant', 'user']


def test_generate_program_returns_validated_tuple(app, monkeypatch):
    valid = json.dumps(
        {
            'program_name': 'Test Plan',
            'description': 'A plan.',
            'sections': [
                {
                    'name': 'Day 1',
                    'exercises': [
                        {
                            'name': 'Squat',
                            'sets': '3',
                            'reps': '5',
                            'weighted': True,
                            'equipment': 'barbell',
                            'description': 'Keep a flat back.',
                        }
                    ],
                }
            ],
        }
    )
    monkeypatch.setattr(
        ai_generator, '_get_completion', lambda c, m: _FakeMessage('end_turn', valid)
    )
    with app.app_context():
        name, description, routine = ai_generator.generate_program('sk-test', _INPUTS)
    assert name == 'Test Plan'
    assert 'Day 1' in routine
