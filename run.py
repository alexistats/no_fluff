from app import create_app, db
from app.models import ExerciseLog, User, UserProgression, Workout

app = create_app()


@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'User': User,
        'Workout': Workout,
        'ExerciseLog': ExerciseLog,
        'UserProgression': UserProgression,
    }


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
