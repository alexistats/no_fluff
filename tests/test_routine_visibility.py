"""Phase 2: per-user routine visibility (de-emphasizing BWF)."""

from app import db
from app.models import UserProgression, Workout


def _hide_bwf(client):
    # Checkbox semantics: absent field = hidden. Keep gym visible.
    return client.post(
        '/settings', data={'action': 'routines', 'show_gym': 'on'}, follow_redirects=True
    )


def test_hiding_bwf_removes_tab_and_gym_becomes_default(logged_in_client):
    client = logged_in_client
    resp = _hide_bwf(client)
    assert b'Routine visibility updated' in resp.data

    resp = client.get('/')
    assert b'routine=bwf' not in resp.data
    assert b'routine=gym' in resp.data
    assert b'Gym Routine' in resp.data  # page title fallback resolved to gym


def test_hidden_routine_still_renders_by_direct_url(logged_in_client):
    client = logged_in_client
    _hide_bwf(client)

    resp = client.get('/?routine=bwf')
    assert resp.status_code == 200
    assert b'BWF Routine' in resp.data

    # The direct visit stored bwf as the session view, but the default must
    # skip it again because it's hidden.
    resp = client.get('/')
    assert b'Gym Routine' in resp.data


def test_cannot_hide_every_builtin_without_an_ai_program(logged_in_client):
    client = logged_in_client
    resp = client.post('/settings', data={'action': 'routines'}, follow_redirects=True)
    assert b'Keep at least one routine visible' in resp.data

    resp = client.get('/')
    assert b'routine=bwf' in resp.data
    assert b'routine=gym' in resp.data


def test_schedule_pickers_exclude_hidden_routines(logged_in_client):
    client = logged_in_client
    _hide_bwf(client)

    resp = client.get('/schedule')
    assert b'<option value="bwf">' not in resp.data
    assert b'<option value="gym">' in resp.data


def test_start_workout_fallback_skips_hidden_routine(logged_in_client, app):
    client = logged_in_client
    _hide_bwf(client)

    client.get('/start_workout')
    with app.app_context():
        assert Workout.query.one().routine_type == 'gym'


# ── Dashboard BWF-progressions gating ──────────────────────────────


def test_dashboard_hides_progressions_without_bwf_activity(logged_in_client):
    # Progressions are seeded at registration, but that alone is not activity.
    resp = logged_in_client.get('/dashboard')
    assert b'BWF Progressions' not in resp.data


def test_dashboard_shows_progressions_after_a_bwf_workout(logged_in_client):
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
        },
    )
    client.get('/end_workout')

    assert b'BWF Progressions' in client.get('/dashboard').data

    # …but not when BWF itself is hidden.
    _hide_bwf(client)
    assert b'BWF Progressions' not in client.get('/dashboard').data


def test_progression_advancement_counts_as_bwf_activity(logged_in_client, app):
    client = logged_in_client
    with app.app_context():
        progression = UserProgression.query.first()
        progression.current_progression = 2
        db.session.commit()

    assert b'BWF Progressions' in client.get('/dashboard').data
