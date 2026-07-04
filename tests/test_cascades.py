"""Deleting a user cascades to everything they own — no orphaned rows."""

from datetime import date

from app import db
from app.models import (
    CustomExercise,
    ExerciseLog,
    GeneratedProgram,
    HiddenExercise,
    RotationEntry,
    User,
    UserApiKey,
    UserProgression,
    Workout,
    WorkoutSchedule,
)


def test_deleting_user_cascades_to_owned_rows(app):
    with app.app_context():
        user = User(username='casc', email='casc@example.com', password_hash='x')
        db.session.add(user)
        db.session.commit()

        workout = Workout(user_id=user.id, routine_type='gym')
        db.session.add(workout)
        db.session.commit()
        db.session.add(ExerciseLog(workout_id=workout.id, exercise_name='Squat'))
        db.session.add_all(
            [
                CustomExercise(user_id=user.id, name='Cable Row'),
                HiddenExercise(user_id=user.id, exercise_name='Leg Press'),
                UserApiKey(user_id=user.id, encrypted_key='x'),
                GeneratedProgram(user_id=user.id, name='Plan', program_json='{}'),
                UserProgression(user_id=user.id, exercise_category='Pull-up'),
                RotationEntry(user_id=user.id, routine_type='gym', position=0),
                WorkoutSchedule(user_id=user.id, routine_type='gym', scheduled_date=date.today()),
            ]
        )
        db.session.commit()

        user_id = user.id
        workout_id = workout.id
        db.session.delete(user)
        db.session.commit()

        assert Workout.query.filter_by(user_id=user_id).count() == 0
        assert ExerciseLog.query.filter_by(workout_id=workout_id).count() == 0
        assert CustomExercise.query.filter_by(user_id=user_id).count() == 0
        assert HiddenExercise.query.filter_by(user_id=user_id).count() == 0
        assert UserApiKey.query.filter_by(user_id=user_id).count() == 0
        assert GeneratedProgram.query.filter_by(user_id=user_id).count() == 0
        assert UserProgression.query.filter_by(user_id=user_id).count() == 0
        assert RotationEntry.query.filter_by(user_id=user_id).count() == 0
        assert WorkoutSchedule.query.filter_by(user_id=user_id).count() == 0
