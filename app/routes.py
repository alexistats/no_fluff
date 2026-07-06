import json
from datetime import UTC, date, datetime, timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    get_flashed_messages,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app import ai_generator, db, limiter
from app.models import (
    BUILTIN_ROUTINES,
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
    leading_int,
)
from app.services import stats
from app.services.email import send_email
from app.services.reset_tokens import generate_reset_token, verify_reset_token
from app.services.routines import active_ai_programs, routine_display_name

main = Blueprint('main', __name__)


def _using_own_api_key():
    """True when the user has their own decryptable key — exempt from the
    shared-key generation limit, since they're spending their own credits."""
    record = UserApiKey.query.filter_by(user_id=current_user.id, provider='anthropic').first()
    return bool(record and record.get_key())


MIN_PASSWORD_LENGTH = 8
MAX_GYM_SETS = 10
ALLOWED_EQUIPMENT = ('barbell', 'dumbbell', 'machine', 'bodyweight')

# What the generation form lets users tick — free-form context for the model,
# not the same thing as the per-exercise equipment enum above.
EQUIPMENT_CHOICES = (
    'full gym membership',
    'barbell and plates',
    'dumbbells',
    'kettlebells',
    'pull-up bar',
    'resistance bands',
    'cardio machines',
    'bodyweight only',
)
EXPERIENCE_LEVELS = ('beginner', 'intermediate', 'advanced')


def _is_ajax():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _routine_with_overlays(base, routine_key):
    """A routine with the user's removals and additions applied."""
    if not current_user.is_authenticated:
        return base

    hidden = {
        h.exercise_name
        for h in HiddenExercise.query.filter_by(user_id=current_user.id, routine_type=routine_key)
    }
    customs = CustomExercise.query.filter_by(
        user_id=current_user.id, routine_type=routine_key
    ).all()

    routine = {
        section: [ex for ex in exercises if ex['name'] not in hidden]
        for section, exercises in base.items()
    }
    for custom in customs:
        routine.setdefault(custom.section, []).append(custom.to_dict())
    return routine


def _gym_routine_for_user():
    """Built-in gym routine with the user's removals and additions applied."""
    return _routine_with_overlays(current_app.config['GYM_ROUTINE_DATA'], 'gym')


def _ai_program_for_key(routine_key, include_draft=False):
    """Resolve an 'ai-<id>' routine key to the current user's program, or None."""
    if not routine_key or not routine_key.startswith('ai-') or not current_user.is_authenticated:
        return None
    try:
        program_id = int(routine_key[3:])
    except ValueError:
        return None
    program = db.session.get(GeneratedProgram, program_id)
    if program is None or program.user_id != current_user.id:
        return None
    if program.is_draft and not include_draft:
        return None
    return program


def _valid_routine_key(routine_key):
    if routine_key in ('bwf', 'gym'):
        return True
    return _ai_program_for_key(routine_key) is not None


def _editable_base_routine(routine_key):
    """Base routine data for keys that support add/remove customization."""
    if routine_key == 'gym':
        return current_app.config['GYM_ROUTINE_DATA']
    program = _ai_program_for_key(routine_key)
    return program.routine_data() if program else None


def _visible_builtin_routines():
    """Built-in routine keys the current user hasn't hidden (all, if anonymous)."""
    if not current_user.is_authenticated:
        return list(BUILTIN_ROUTINES)
    return current_user.visible_builtin_routines()


def _default_routine_view():
    """Last routine the user interacted with that is still visible, falling back
    to the first visible built-in, then the first accepted AI program.

    Hidden routines stay reachable by direct URL — they just never win the
    default.
    """
    if not current_user.is_authenticated:
        return 'bwf'

    def usable(key):
        if not key or not _valid_routine_key(key):
            return False
        return key not in BUILTIN_ROUTINES or not current_user.is_routine_hidden(key)

    view = session.get('current_routine_view')
    if usable(view):
        return view
    last_workout = (
        Workout.query.filter_by(user_id=current_user.id).order_by(Workout.id.desc()).first()
    )
    if last_workout and usable(last_workout.routine_type):
        return last_workout.routine_type
    visible = current_user.visible_builtin_routines()
    if visible:
        return visible[0]
    programs = active_ai_programs(current_user)
    if programs:
        return programs[0].routine_key
    return 'bwf'


def _today_plan():
    """Return the scheduled or rotation-suggested routine for today, or None.

    Returns a dict: {routine_type, source} where source is 'scheduled' or 'rotation'.
    """
    if not current_user.is_authenticated:
        return None
    today = date.today()
    scheduled = WorkoutSchedule.query.filter_by(
        user_id=current_user.id, scheduled_date=today
    ).first()
    if scheduled and _valid_routine_key(scheduled.routine_type):
        return {'routine_type': scheduled.routine_type, 'source': 'scheduled'}

    rotation = (
        RotationEntry.query.filter_by(user_id=current_user.id)
        .order_by(RotationEntry.position)
        .all()
    )
    if not rotation:
        return None

    last_workout = (
        Workout.query.filter_by(user_id=current_user.id).order_by(Workout.id.desc()).first()
    )
    if last_workout is None:
        candidate = rotation[0].routine_type
    else:
        last_type = last_workout.routine_type
        positions = [r.routine_type for r in rotation]
        try:
            idx = positions.index(last_type)
            candidate = positions[(idx + 1) % len(positions)]
        except ValueError:
            candidate = positions[0]

    if _valid_routine_key(candidate):
        return {'routine_type': candidate, 'source': 'rotation'}
    return None


@main.route('/')
def home():
    routine = request.args.get('routine')
    if not routine or not _valid_routine_key(routine):
        routine = _default_routine_view()
    if current_user.is_authenticated:
        session['current_routine_view'] = routine

    hidden_count = 0
    ai_program = None
    if routine == 'bwf':
        routine_data = current_app.config['ROUTINE_DATA']
    else:
        if routine == 'gym':
            base = current_app.config['GYM_ROUTINE_DATA']
        else:
            ai_program = _ai_program_for_key(routine)
            base = ai_program.routine_data()
        routine_data = _routine_with_overlays(base, routine)
        if current_user.is_authenticated:
            hidden_count = HiddenExercise.query.filter_by(
                user_id=current_user.id, routine_type=routine
            ).count()

    ai_programs = active_ai_programs(current_user) if current_user.is_authenticated else []

    last_logs = {}
    user_progressions = {}
    progression_data = {}
    today_plan = None

    if current_user.is_authenticated:
        all_names = [ex['name'] for exs in routine_data.values() for ex in exs]
        subq = (
            db.session.query(ExerciseLog.exercise_name, func.max(ExerciseLog.id).label('max_id'))
            .join(Workout)
            .filter(Workout.user_id == current_user.id, ExerciseLog.exercise_name.in_(all_names))
            .group_by(ExerciseLog.exercise_name)
            .subquery()
        )
        last_logs = {
            log.exercise_name: log
            for log in ExerciseLog.query.join(subq, ExerciseLog.id == subq.c.max_id).all()
        }

        if routine == 'bwf':
            progression_data = current_app.config['PROGRESSION_DATA']
            user_progressions = {
                p.exercise_category: p
                for p in UserProgression.query.filter_by(user_id=current_user.id).all()
            }

        plan = _today_plan()
        if plan:
            plan['label'] = routine_display_name(plan['routine_type'], ai_programs)
            today_plan = plan

    return render_template(
        'home.html',
        routine=routine_data,
        routine_type=routine,
        last_logs=last_logs,
        user_progressions=user_progressions,
        progression_data=progression_data,
        hidden_count=hidden_count,
        ai_program=ai_program,
        ai_programs=ai_programs,
        today_plan=today_plan,
        visible_builtins=_visible_builtin_routines(),
    )


@main.route('/sw.js')
def service_worker():
    # Served from the root so its scope covers the whole app (a file under
    # /static/ would be scoped to /static/ and couldn't handle navigations).
    response = current_app.send_static_file('js/sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@main.route('/offline')
def offline():
    return render_template('offline.html')


@main.route('/login', methods=['GET', 'POST'])
@limiter.limit('5/minute', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.home'))
        else:
            flash('Invalid username or password')

    return render_template('login.html')


@main.route('/register', methods=['GET', 'POST'])
@limiter.limit('5/minute', methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if not password or len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.')
            return redirect(url_for('main.register'))

        # One generic message so we don't reveal which accounts already exist.
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Username or email already in use')
            return redirect(url_for('main.register'))

        user = User(username=username, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        progression_data = current_app.config['PROGRESSION_DATA']
        for category in progression_data:
            db.session.add(
                UserProgression(
                    user_id=user.id,
                    exercise_category=category,
                    current_progression=1,
                    current_reps=5,
                )
            )
        db.session.commit()

        flash('Registration successful! Please log in.')
        return redirect(url_for('main.login'))

    return render_template('register.html')


@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.home'))


def _external_url_for(endpoint, **values):
    """Absolute URL for use in emails.

    Prefers the configured APP_BASE_URL (trusted) over the request host, so a
    spoofed Host header can't steer emailed links; local dev falls back to the
    request host.
    """
    path = url_for(endpoint, **values)
    base = current_app.config.get('APP_BASE_URL')
    if base:
        return base.rstrip('/') + path
    return request.url_root.rstrip('/') + path


@main.route('/forgot_password', methods=['GET', 'POST'])
@limiter.limit('3/hour', methods=['POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        email_addr = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email_addr).first() if email_addr else None
        if user:
            reset_url = _external_url_for('main.reset_password', token=generate_reset_token(user))
            send_email(
                user.email,
                'Reset your NoFluff password',
                f'Reset your NoFluff password: {reset_url}\n\n'
                'The link expires in 1 hour. If this was not you, ignore this email.',
            )
        # One message either way — don't reveal which emails are registered.
        flash('If that email is registered, a reset link is on its way.')
        return redirect(url_for('main.login'))

    return render_template('forgot_password.html')


@main.route('/reset_password/<token>', methods=['GET', 'POST'])
@limiter.limit('10/hour', methods=['POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    user = verify_reset_token(token)
    if user is None:
        flash('That reset link is invalid or has expired — request a new one.')
        return redirect(url_for('main.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.')
        elif password != request.form.get('confirm_password', ''):
            flash('Passwords do not match.')
        else:
            user.password_hash = generate_password_hash(password)
            db.session.commit()
            flash('Password updated — log in with your new password.')
            return redirect(url_for('main.login'))

    return render_template('reset_password.html', token=token)


@main.route('/exercise/<section>/<int:index>')
def exercise(section, index):
    routine = request.args.get('routine', 'bwf')
    if routine == 'gym':
        return _gym_style_exercise_view(section, index, _gym_routine_for_user(), 'gym')
    program = _ai_program_for_key(routine)
    if program is not None:
        routine_data = _routine_with_overlays(program.routine_data(), routine)
        return _gym_style_exercise_view(section, index, routine_data, routine)
    return _bwf_exercise_view(section, index)


def _gym_style_exercise_view(section, index, routine_data, routine_key):
    exercises = routine_data.get(section, [])
    if index >= len(exercises):
        flash('Exercise not found.')
        return redirect(url_for('main.home', routine=routine_key))
    exercise_obj = exercises[index]
    # Gym/AI routines have no progressions; exercise.html guards on these being
    # absent (Jinja treats the missing vars as falsy).
    return render_template(
        'exercise.html',
        exercise=exercise_obj,
        section=section,
        routine=routine_key,
    )


def _bwf_exercise_view(section, index):
    routine_data = current_app.config['ROUTINE_DATA']
    exercise_obj = routine_data[section][index]

    progression_data = None
    if exercise_obj['name'].endswith('Progression'):
        progression_data = current_app.config['PROGRESSION_DATA'].get(exercise_obj['name'], [])

    user_progression = None
    if current_user.is_authenticated and progression_data:
        user_progression = UserProgression.query.filter_by(
            user_id=current_user.id, exercise_category=exercise_obj['name']
        ).first()

    return render_template(
        'exercise.html',
        exercise=exercise_obj,
        section=section,
        routine='bwf',
        progression_data=progression_data,
        user_progression=user_progression,
    )


def _form_routine_key():
    """Customization target from the form: 'gym' or a valid 'ai-<id>' key."""
    routine_key = request.form.get('routine', 'gym')
    if routine_key != 'gym' and _ai_program_for_key(routine_key) is None:
        return 'gym'
    return routine_key


@main.route('/routine/add_exercise', methods=['POST'])
@login_required
def add_exercise():
    routine_key = _form_routine_key()
    section = request.form.get('section', '').strip()
    name = request.form.get('name', '').strip()

    base = _editable_base_routine(routine_key)
    if not name or base is None or section not in base:
        flash('Exercise name and a valid section are required.')
        return redirect(url_for('main.home', routine=routine_key))

    visible_names = {
        ex['name'].lower()
        for exercises in _routine_with_overlays(base, routine_key).values()
        for ex in exercises
    }
    if name.lower() in visible_names:
        flash(f'"{name}" is already in your routine.')
        return redirect(url_for('main.home', routine=routine_key))

    sets = request.form.get('sets', type=int) or 3
    sets = max(1, min(sets, MAX_GYM_SETS))
    reps = request.form.get('reps', '').strip() or '8-12'
    equipment = request.form.get('equipment', 'machine')
    if equipment not in ALLOWED_EQUIPMENT:
        equipment = 'machine'

    db.session.add(
        CustomExercise(
            user_id=current_user.id,
            routine_type=routine_key,
            section=section,
            name=name,
            sets=sets,
            reps=reps[:20],
            weighted=(equipment != 'bodyweight'),
            equipment=equipment,
            description=request.form.get('description', '').strip(),
        )
    )
    db.session.commit()
    flash(f'Added "{name}" to {section}.')
    return redirect(url_for('main.home', routine=routine_key))


@main.route('/routine/remove_exercise', methods=['POST'])
@login_required
def remove_exercise():
    routine_key = _form_routine_key()
    name = request.form.get('name', '').strip()
    if not name:
        return redirect(url_for('main.home', routine=routine_key))

    custom = CustomExercise.query.filter_by(
        user_id=current_user.id, routine_type=routine_key, name=name
    ).first()
    if custom:
        db.session.delete(custom)
    else:
        already_hidden = HiddenExercise.query.filter_by(
            user_id=current_user.id, routine_type=routine_key, exercise_name=name
        ).first()
        if not already_hidden:
            db.session.add(
                HiddenExercise(
                    user_id=current_user.id,
                    routine_type=routine_key,
                    exercise_name=name,
                )
            )
    db.session.commit()
    flash(f'Removed "{name}" from your routine.')
    return redirect(url_for('main.home', routine=routine_key))


@main.route('/routine/restore_exercises', methods=['POST'])
@login_required
def restore_exercises():
    routine_key = _form_routine_key()
    HiddenExercise.query.filter_by(user_id=current_user.id, routine_type=routine_key).delete()
    db.session.commit()
    flash('Removed exercises restored.')
    return redirect(url_for('main.home', routine=routine_key))


@main.route('/start_workout')
@login_required
def start_workout():
    routine_type = request.args.get('routine_type', session.get('current_routine_view'))
    if not routine_type or not _valid_routine_key(routine_type):
        routine_type = _default_routine_view()
    workout = Workout(user_id=current_user.id, routine_type=routine_type)
    db.session.add(workout)
    db.session.commit()

    session['current_workout_id'] = workout.id
    session['current_routine_type'] = routine_type
    session['current_routine_view'] = routine_type

    flash('Workout started!')
    return redirect(url_for('main.home', routine=routine_type))


@main.route('/end_workout')
@login_required
def end_workout():
    if 'current_workout_id' in session:
        workout_id = session.pop('current_workout_id')
        routine_type = session.pop('current_routine_type', 'bwf')
        workout = db.session.get(Workout, workout_id)

        if workout and workout.exercises.count() == 0:
            db.session.delete(workout)
            db.session.commit()
            flash('Workout cancelled.')
        else:
            flash('Workout completed!')

        return redirect(url_for('main.home', routine=routine_type))

    return redirect(url_for('main.home'))


@main.route('/log_exercise/<exercise_name>', methods=['POST'])
@login_required
def log_exercise(exercise_name):
    if 'current_workout_id' not in session:
        if _is_ajax():
            return jsonify({'status': 'error', 'message': 'No active workout'}), 400
        flash('No active workout. Please start a workout first.')
        return redirect(url_for('main.home'))

    workout_id = session['current_workout_id']
    routine = request.form.get('routine', 'bwf')
    section = request.form.get('section', '')
    index = request.form.get('index')
    rest_period = 60 if 'Core' in section else 90

    # AI-generated programs use the gym exercise schema, so they log the same way
    if routine == 'bwf':
        result = _log_bwf_exercise(exercise_name, workout_id)
    else:
        result = _log_gym_exercise(exercise_name, workout_id)

    if _is_ajax():
        get_flashed_messages()  # discard — flash queue unused for AJAX responses
        return jsonify(
            {
                'status': 'ok' if result.get('ok') else 'error',
                'message': result.get('message', ''),
                'exercise_name': exercise_name,
                'sets_completed': result.get('sets_completed', 0),
                'rest_period': rest_period,
                'advanced': result.get('advanced', False),
                'new_progression': result.get('new_progression'),
            }
        )

    return redirect(url_for('main.exercise', section=section, index=index, routine=routine))


def parse_gym_sets(form):
    """Return (weights, reps) lists from numbered form fields.
    A set counts when reps are present; weight is optional."""
    weights, reps = [], []
    for i in range(1, MAX_GYM_SETS + 1):
        reps_str = form.get(f'reps_set_{i}', '').strip()
        weight_str = form.get(f'weight_set_{i}', '').strip()
        if reps_str:
            reps.append(reps_str)
            weights.append(weight_str if weight_str else '0')
    return weights, reps


def _log_gym_exercise(exercise_name, workout_id):
    weights, reps = parse_gym_sets(request.form)
    if not reps:
        flash('Please fill in at least one set.')
        return {'ok': False, 'sets_completed': 0, 'message': 'Please fill in at least one set.'}

    has_weights = any(w not in ('', '0') for w in weights)
    weight_unit = request.form.get('weight_unit', 'lbs')

    db.session.add(
        ExerciseLog(
            exercise_name=exercise_name,
            sets_completed=len(reps),
            reps_per_set=','.join(reps),
            weight_per_set=','.join(weights) if has_weights else None,
            weight_unit=weight_unit if has_weights else None,
            progression_level=None,
            notes=request.form.get('notes', '').strip()[:500],
            workout_id=workout_id,
        )
    )
    db.session.commit()
    flash('Exercise logged!')
    return {'ok': True, 'sets_completed': len(reps), 'message': 'Exercise logged!'}


def _log_bwf_exercise(exercise_name, workout_id):
    progression_level = request.form.get('progression_level', type=int)

    # BWF logs only reps (no weight) — reuse the shared set parser and drop weights.
    _, reps_list = parse_gym_sets(request.form)

    db.session.add(
        ExerciseLog(
            exercise_name=exercise_name,
            sets_completed=len(reps_list),
            reps_per_set=','.join(reps_list),
            progression_level=progression_level,
            notes=request.form.get('notes', '').strip()[:500],
            workout_id=workout_id,
        )
    )

    advanced, new_name = maybe_advance_progression(current_user, exercise_name, reps_list)
    db.session.commit()
    flash('Exercise logged successfully!')
    return {
        'ok': True,
        'sets_completed': len(reps_list),
        'message': 'Exercise logged!',
        'advanced': advanced,
        'new_progression': new_name,
    }


def maybe_advance_progression(user, exercise_name, reps_list):
    """Advance level after 3+ sets of 8+ reps. Returns (advanced, new_name)."""
    if not exercise_name.endswith('Progression'):
        return False, None
    reps = [leading_int(r) for r in reps_list]
    if len(reps) < 3 or not all(r is not None and r >= 8 for r in reps):
        return False, None

    user_progression = UserProgression.query.filter_by(
        user_id=user.id, exercise_category=exercise_name
    ).first()
    if not user_progression:
        return False, None

    progression_data = current_app.config['PROGRESSION_DATA'].get(exercise_name, [])
    max_level = len(progression_data)

    if user_progression.current_progression < max_level:
        user_progression.current_progression += 1
        user_progression.current_reps = 5
        user_progression.last_updated = datetime.now(UTC)
        next_name = progression_data[user_progression.current_progression - 1]['name']
        flash(f'Congratulations! You advanced to: {next_name}')
        return True, next_name

    return False, None


@main.route('/dashboard')
@login_required
def dashboard():
    user_id = current_user.id
    ai_programs = active_ai_programs(current_user)
    today = datetime.now(UTC).date()

    counts = stats.workout_counts(user_id, today)
    freq_labels, freq_values = stats.weekly_frequency(user_id, today)
    recent_workouts = (
        Workout.query.filter_by(user_id=user_id).order_by(Workout.date.desc()).limit(10).all()
    )

    # Progressions are seeded for everyone at registration, so gate the BWF
    # section on actual BWF activity (a workout or an advancement), and on the
    # routine being visible at all.
    user_progressions = UserProgression.query.filter_by(user_id=user_id).all()
    has_bwf_activity = db.session.query(Workout.id).filter_by(
        user_id=user_id, routine_type='bwf'
    ).first() is not None or any(p.current_progression > 1 for p in user_progressions)
    show_bwf_progressions = not current_user.is_routine_hidden('bwf') and has_bwf_activity

    return render_template(
        'dashboard.html',
        user_progressions=user_progressions,
        show_bwf_progressions=show_bwf_progressions,
        progression_data=current_app.config['PROGRESSION_DATA'],
        recent_workouts=recent_workouts,
        total_workouts=counts['total'],
        workouts_this_week=counts['this_week'],
        workouts_this_month=counts['this_month'],
        freq_labels=freq_labels,
        freq_values=freq_values,
        routine_breakdown=stats.routine_breakdown(user_id, ai_programs),
        top_exercises=stats.top_exercises(user_id),
        weight_trends=stats.weight_trends(user_id),
    )


# ── Scheduling ────────────────────────────────────────────────


@main.route('/schedule')
@login_required
def schedule():
    ai_programs = active_ai_programs(current_user)

    rotation = (
        RotationEntry.query.filter_by(user_id=current_user.id)
        .order_by(RotationEntry.position)
        .all()
    )

    today = date.today()
    two_weeks = [today + timedelta(days=i) for i in range(14)]
    scheduled = {
        s.scheduled_date: s
        for s in WorkoutSchedule.query.filter(
            WorkoutSchedule.user_id == current_user.id,
            WorkoutSchedule.scheduled_date >= today,
            WorkoutSchedule.scheduled_date <= today + timedelta(days=13),
        ).all()
    }

    calendar_days = []
    for d in two_weeks:
        entry = scheduled.get(d)
        calendar_days.append(
            {
                'date': d,
                'date_str': d.strftime('%Y-%m-%d'),
                'label': d.strftime('%a %-d'),
                'routine_type': entry.routine_type if entry else None,
                'schedule_id': entry.id if entry else None,
            }
        )

    # Full list for labelling existing entries (a hidden routine already in the
    # rotation or calendar keeps working); pickers only offer visible routines.
    all_routines = [
        {'key': 'bwf', 'label': 'BWF'},
        {'key': 'gym', 'label': 'Gym'},
    ] + [{'key': p.routine_key, 'label': p.name} for p in ai_programs]
    visible = set(_visible_builtin_routines())
    pickable_routines = [
        r for r in all_routines if r['key'] in visible or r['key'].startswith('ai-')
    ]

    return render_template(
        'schedule.html',
        rotation=rotation,
        calendar_days=calendar_days,
        all_routines=all_routines,
        pickable_routines=pickable_routines,
        today=today,
    )


@main.route('/schedule/rotation', methods=['POST'])
@login_required
def save_rotation():
    data = request.get_json(silent=True) or {}
    routine_types = data.get('rotation', [])
    # Validate each entry
    valid = [rt for rt in routine_types if _valid_routine_key(rt)]
    RotationEntry.query.filter_by(user_id=current_user.id).delete()
    for i, rt in enumerate(valid):
        db.session.add(
            RotationEntry(
                user_id=current_user.id,
                routine_type=rt,
                position=i,
            )
        )
    db.session.commit()
    return jsonify({'status': 'ok'})


@main.route('/schedule/plan', methods=['POST'])
@login_required
def plan_workout():
    data = request.get_json(silent=True) or {}
    date_str = data.get('date', '')
    routine_type = data.get('routine_type', '')
    try:
        scheduled_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid date'}), 400
    if not _valid_routine_key(routine_type):
        return jsonify({'status': 'error', 'message': 'Invalid routine'}), 400

    existing = WorkoutSchedule.query.filter_by(
        user_id=current_user.id, scheduled_date=scheduled_date
    ).first()
    if existing:
        existing.routine_type = routine_type
        entry = existing
    else:
        entry = WorkoutSchedule(
            user_id=current_user.id,
            routine_type=routine_type,
            scheduled_date=scheduled_date,
        )
        db.session.add(entry)
    db.session.commit()
    return jsonify({'status': 'ok', 'id': entry.id})


@main.route('/schedule/plan/<int:schedule_id>', methods=['DELETE'])
@login_required
def unplan_workout(schedule_id):
    entry = db.session.get(WorkoutSchedule, schedule_id)
    if entry and entry.user_id == current_user.id:
        db.session.delete(entry)
        db.session.commit()
    return jsonify({'status': 'ok'})


@main.route('/workout/<int:workout_id>')
@login_required
def view_workout(workout_id):
    workout = db.session.get(Workout, workout_id)
    if workout is None:
        flash('Workout not found.')
        return redirect(url_for('main.dashboard'))

    if workout.user_id != current_user.id:
        flash('You do not have permission to view this workout.')
        return redirect(url_for('main.dashboard'))

    exercise_logs = ExerciseLog.query.filter_by(workout_id=workout_id).all()
    progression_data = current_app.config['PROGRESSION_DATA']

    # Resolve the progression name per log here so the template doesn't have to
    # encode the "name ends with 'Progression'" business rule.
    progression_names = {}
    for log in exercise_logs:
        if not log.exercise_name.endswith('Progression'):
            continue
        levels = progression_data.get(log.exercise_name, [])
        match = next((lv for lv in levels if lv.get('level') == log.progression_level), None)
        if match:
            progression_names[log.id] = match['name']

    return render_template(
        'workout_detail.html',
        workout=workout,
        exercise_logs=exercise_logs,
        progression_names=progression_names,
    )


@main.route('/workout/<int:workout_id>/delete', methods=['POST'])
@login_required
def delete_workout(workout_id):
    workout = db.session.get(Workout, workout_id)
    if workout is None or workout.user_id != current_user.id:
        flash('Workout not found.')
        return redirect(url_for('main.dashboard'))

    # Deleting the in-progress workout also ends the logging session.
    if session.get('current_workout_id') == workout_id:
        session.pop('current_workout_id', None)
        session.pop('current_routine_type', None)

    db.session.delete(workout)  # ORM cascade removes its ExerciseLog rows
    db.session.commit()
    flash('Workout deleted.')
    return redirect(url_for('main.dashboard'))


# ── AI program generation ──────────────────────────────────────────────


def _owned_program_or_none(program_id):
    program = db.session.get(GeneratedProgram, program_id)
    if program is None or program.user_id != current_user.id:
        return None
    return program


def _generation_inputs_from_form(form):
    days = form.get('days_per_week', type=int) or 3
    minutes = form.get('session_length', type=int) or 60
    experience = form.get('experience', 'beginner')
    return {
        'goal': form.get('goal', '').strip()[:200],
        'equipment': [e for e in form.getlist('equipment') if e in EQUIPMENT_CHOICES],
        'days_per_week': max(1, min(days, 7)),
        'session_length': max(15, min(minutes, 180)),
        'experience': experience if experience in EXPERIENCE_LEVELS else 'beginner',
        'notes': form.get('notes', '').strip()[:500],
    }


@main.route('/generate', methods=['GET', 'POST'])
@login_required
@limiter.limit('3/hour', methods=['POST'], exempt_when=_using_own_api_key)
def generate():
    api_key = ai_generator.resolve_api_key(current_user)

    if request.method == 'GET':
        return render_template(
            'generate.html',
            has_api_key=bool(api_key),
            equipment_choices=EQUIPMENT_CHOICES,
            experience_levels=EXPERIENCE_LEVELS,
        )

    if not api_key:
        flash('No Claude API key available. Add yours in Settings first.')
        return redirect(url_for('main.settings'))

    inputs = _generation_inputs_from_form(request.form)
    if not inputs['goal']:
        flash('Tell the coach what you are training for.')
        return redirect(url_for('main.generate'))

    try:
        name, description, routine = ai_generator.generate_program(api_key, inputs)
    except ai_generator.GenerationError as exc:
        current_app.logger.warning('Program generation failed: %s', exc)
        flash(str(exc))
        return redirect(url_for('main.generate'))

    # Abandoned drafts are dead weight — keep at most one per user
    GeneratedProgram.query.filter_by(user_id=current_user.id, is_draft=True).delete()
    program = GeneratedProgram(
        user_id=current_user.id,
        name=name,
        goal=inputs['goal'],
        description=description,
        program_json=json.dumps(routine),
        inputs_json=json.dumps(inputs),
        is_draft=True,
    )
    db.session.add(program)
    db.session.commit()
    return redirect(url_for('main.preview_program', program_id=program.id))


@main.route('/generate/preview/<int:program_id>')
@login_required
def preview_program(program_id):
    program = _owned_program_or_none(program_id)
    if program is None:
        flash('Program not found.')
        return redirect(url_for('main.home'))
    return render_template(
        'preview_program.html',
        program=program,
        routine=program.routine_data(),
    )


@main.route('/generate/accept/<int:program_id>', methods=['POST'])
@login_required
def accept_program(program_id):
    program = _owned_program_or_none(program_id)
    if program is None:
        flash('Program not found.')
        return redirect(url_for('main.home'))
    program.is_draft = False
    db.session.commit()
    flash(f'"{program.name}" saved — time to train!')
    return redirect(url_for('main.home', routine=program.routine_key))


@main.route('/generate/retry/<int:program_id>', methods=['POST'])
@login_required
@limiter.limit('3/hour', methods=['POST'], exempt_when=_using_own_api_key)
def retry_program(program_id):
    program = _owned_program_or_none(program_id)
    if program is None:
        flash('Program not found.')
        return redirect(url_for('main.home'))

    feedback = request.form.get('feedback', '').strip()[:500]
    if not feedback:
        flash('Tell the coach what to change.')
        return redirect(url_for('main.preview_program', program_id=program.id))

    api_key = ai_generator.resolve_api_key(current_user)
    if not api_key:
        flash('No Claude API key available. Add yours in Settings first.')
        return redirect(url_for('main.settings'))

    try:
        name, description, routine = ai_generator.generate_program(
            api_key, program.inputs(), previous_program=program.routine_data(), feedback=feedback
        )
    except ai_generator.GenerationError as exc:
        current_app.logger.warning('Program regeneration failed: %s', exc)
        flash(str(exc))
        return redirect(url_for('main.preview_program', program_id=program.id))

    program.name = name
    program.description = description
    program.program_json = json.dumps(routine)
    db.session.commit()
    flash('Program updated with your feedback.')
    return redirect(url_for('main.preview_program', program_id=program.id))


@main.route('/program/delete/<int:program_id>', methods=['POST'])
@login_required
def delete_program(program_id):
    program = _owned_program_or_none(program_id)
    if program is None:
        flash('Program not found.')
        return redirect(url_for('main.home'))

    routine_key = program.routine_key
    CustomExercise.query.filter_by(user_id=current_user.id, routine_type=routine_key).delete()
    HiddenExercise.query.filter_by(user_id=current_user.id, routine_type=routine_key).delete()
    db.session.delete(program)
    db.session.commit()
    if session.get('current_routine_view') == routine_key:
        session.pop('current_routine_view')
    flash(f'Deleted "{program.name}". Workout history is kept.')
    return redirect(url_for('main.home'))


@main.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    record = UserApiKey.query.filter_by(user_id=current_user.id, provider='anthropic').first()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'clear':
            if record:
                db.session.delete(record)
                db.session.commit()
            flash('Your API key was removed.')
        elif action == 'routines':
            hidden = [key for key in BUILTIN_ROUTINES if not request.form.get(f'show_{key}')]
            if len(hidden) == len(BUILTIN_ROUTINES) and not active_ai_programs(current_user):
                flash('Keep at least one routine visible (or save an AI program first).')
            else:
                current_user.hidden_routines = ','.join(hidden)
                db.session.commit()
                if session.get('current_routine_view') in hidden:
                    session.pop('current_routine_view')
                flash('Routine visibility updated.')
        else:
            raw = request.form.get('api_key', '').strip()
            if not raw:
                flash('Enter an API key to save.')
            else:
                if record is None:
                    record = UserApiKey(user_id=current_user.id, provider='anthropic')
                    db.session.add(record)
                record.set_key(raw)
                db.session.commit()
                flash('API key saved.')
        return redirect(url_for('main.settings'))

    key_hint = record.key_hint() if record else None
    routine_prefs = [
        {
            'key': key,
            'label': routine_display_name(key, []),
            'visible': not current_user.is_routine_hidden(key),
        }
        for key in BUILTIN_ROUTINES
    ]
    return render_template(
        'settings.html',
        key_hint=key_hint,
        key_undecryptable=bool(record) and key_hint is None,
        server_key_available=bool(current_app.config.get('ANTHROPIC_API_KEY')),
        routine_prefs=routine_prefs,
    )
