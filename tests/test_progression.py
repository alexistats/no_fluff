from app import db
from app.models import User, UserProgression
from app.routes import maybe_advance_progression, parse_gym_sets


class FakeForm(dict):
    def get(self, key, default=''):
        return dict.get(self, key, default)


def test_parse_gym_sets_collects_filled_sets():
    form = FakeForm(
        {
            'weight_set_1': '95',
            'reps_set_1': '10',
            'weight_set_2': '95',
            'reps_set_2': '8',
            'weight_set_3': '',
            'reps_set_3': '',
        }
    )
    weights, reps = parse_gym_sets(form)
    assert weights == ['95', '95']
    assert reps == ['10', '8']


def test_parse_gym_sets_bodyweight_defaults_weight_to_zero():
    form = FakeForm({'reps_set_1': '20'})
    weights, reps = parse_gym_sets(form)
    assert weights == ['0']
    assert reps == ['20']


def _make_user_with_progression(app, category, level=1):
    user = User(username='prog', email='prog@example.com', password_hash='x')
    db.session.add(user)
    db.session.commit()
    progression = UserProgression(
        user_id=user.id,
        exercise_category=category,
        current_progression=level,
        current_reps=8,
    )
    db.session.add(progression)
    db.session.commit()
    return user, progression


def test_advances_on_three_sets_of_eight(app):
    with app.test_request_context():
        user, progression = _make_user_with_progression(app, 'Pull-up Progression')
        maybe_advance_progression(user, 'Pull-up Progression', ['8', '8', '8'])
        assert progression.current_progression == 2
        assert progression.current_reps == 5


def test_no_advance_below_eight_reps(app):
    with app.test_request_context():
        user, progression = _make_user_with_progression(app, 'Pull-up Progression')
        maybe_advance_progression(user, 'Pull-up Progression', ['8', '8', '7'])
        assert progression.current_progression == 1


def test_no_advance_with_fewer_than_three_sets(app):
    with app.test_request_context():
        user, progression = _make_user_with_progression(app, 'Pull-up Progression')
        maybe_advance_progression(user, 'Pull-up Progression', ['10', '10'])
        assert progression.current_progression == 1


def test_no_advance_past_max_level(app):
    with app.app_context():
        max_level = len(app.config['PROGRESSION_DATA']['Pull-up Progression'])
    with app.test_request_context():
        user, progression = _make_user_with_progression(app, 'Pull-up Progression', level=max_level)
        maybe_advance_progression(user, 'Pull-up Progression', ['8', '8', '8'])
        assert progression.current_progression == max_level


def test_ignores_non_progression_exercises(app):
    with app.test_request_context():
        user, progression = _make_user_with_progression(app, 'Pull-up Progression')
        maybe_advance_progression(user, 'Bench Press', ['8', '8', '8'])
        assert progression.current_progression == 1
