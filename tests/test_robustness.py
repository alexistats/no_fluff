"""Phase 3 crash fixes: tolerant reps parsing and malformed JSON bodies."""

from app.models import ExerciseLog


def test_get_reps_list_tolerates_timed_holds():
    # Free-form BWF/AI reps like "30s" must not crash on read.
    log = ExerciseLog(reps_per_set='30s,8,,10')
    assert log.get_reps_list() == [30, 8, 10]


def test_get_reps_list_empty():
    assert ExerciseLog(reps_per_set=None).get_reps_list() == []


def test_plan_workout_rejects_malformed_json(logged_in_client):
    resp = logged_in_client.post('/schedule/plan', data='not json', content_type='application/json')
    assert resp.status_code == 400


def test_save_rotation_tolerates_malformed_json(logged_in_client):
    resp = logged_in_client.post(
        '/schedule/rotation', data='not json', content_type='application/json'
    )
    assert resp.status_code == 200
