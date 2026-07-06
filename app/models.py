import base64
import hashlib
import json
import re
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from flask_login import UserMixin

from app import db, login_manager

_LEADING_INT = re.compile(r'-?\d+')

# Built-in routine keys, in display order. AI programs ('ai-<id>') are per-user
# and live in GeneratedProgram; visibility preferences only apply to these.
BUILTIN_ROUTINES = ('bwf', 'gym')


def leading_int(token):
    """First integer in a token ('30s' -> 30, '8' -> 8), or None if none.

    Reps are usually plain integers, but AI/BWF entries can carry timed holds
    like '30s'; parsing tolerantly keeps those from crashing reads.
    """
    match = _LEADING_INT.search(str(token))
    return int(match.group()) if match else None


def utc_now():
    return datetime.now(UTC)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(120), unique=True, index=True)
    password_hash = db.Column(db.String(256))
    # Comma-separated BUILTIN_ROUTINES keys the user has hidden from tabs,
    # pickers, and the dashboard. Hiding never deletes history, and direct
    # URLs to a hidden routine still work.
    hidden_routines = db.Column(db.String(100), default='')
    # Calendar feed + email reminders. ics_token is the secret in the feed URL
    # (None = feed disabled); reminder_time is local 'HH:MM' with the user's
    # UTC offset captured from the browser; last_reminded_on (a *local* date)
    # makes the hourly reminder job idempotent.
    ics_token = db.Column(db.String(64), unique=True, index=True, nullable=True)
    reminder_enabled = db.Column(db.Boolean, default=False)
    reminder_time = db.Column(db.String(5), default='07:00')
    tz_offset_minutes = db.Column(db.Integer, default=0)  # minutes east of UTC
    last_reminded_on = db.Column(db.Date, nullable=True)

    def hidden_routine_keys(self):
        return {key for key in (self.hidden_routines or '').split(',') if key}

    def is_routine_hidden(self, routine_key):
        return routine_key in self.hidden_routine_keys()

    def visible_builtin_routines(self):
        hidden = self.hidden_routine_keys()
        return [key for key in BUILTIN_ROUTINES if key not in hidden]

    # Deleting a user cleans up everything owned by them (cascade is ORM-level;
    # no ON DELETE in the schema, so it works the same on SQLite and Postgres).
    workouts = db.relationship(
        'Workout', backref='user', lazy='dynamic', cascade='all, delete-orphan'
    )
    progressions = db.relationship(
        'UserProgression', backref='user', lazy='dynamic', cascade='all, delete-orphan'
    )
    custom_exercises = db.relationship(
        'CustomExercise', backref='user', lazy='dynamic', cascade='all, delete-orphan'
    )
    hidden_exercises = db.relationship(
        'HiddenExercise', backref='user', lazy='dynamic', cascade='all, delete-orphan'
    )
    api_key = db.relationship(
        'UserApiKey', backref='user', uselist=False, cascade='all, delete-orphan'
    )
    generated_programs = db.relationship(
        'GeneratedProgram', backref='user', lazy='dynamic', cascade='all, delete-orphan'
    )
    rotation_entries = db.relationship(
        'RotationEntry', backref='user', lazy='dynamic', cascade='all, delete-orphan'
    )
    scheduled_workouts = db.relationship(
        'WorkoutSchedule', backref='user', lazy='dynamic', cascade='all, delete-orphan'
    )


class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=utc_now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    routine_type = db.Column(db.String(20), default='bwf')
    exercises = db.relationship(
        'ExerciseLog', backref='workout', lazy='dynamic', cascade='all, delete-orphan'
    )

    def formatted_date(self):
        return self.date.strftime('%Y-%m-%d %H:%M')


class ExerciseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exercise_name = db.Column(db.String(100))
    sets_completed = db.Column(db.Integer)
    reps_per_set = db.Column(db.String(100))  # comma-separated
    weight_per_set = db.Column(db.String(200), nullable=True)  # comma-separated, gym only
    weight_unit = db.Column(db.String(5), nullable=True)  # 'lbs' or 'kg'
    progression_level = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text)
    workout_id = db.Column(db.Integer, db.ForeignKey('workout.id'), index=True)

    def get_reps_list(self):
        if not self.reps_per_set:
            return []
        values = (leading_int(t) for t in self.reps_per_set.split(','))
        return [v for v in values if v is not None]

    def get_weights_list(self):
        if not self.weight_per_set:
            return []
        return [float(w) for w in self.weight_per_set.split(',') if w]


class CustomExercise(db.Model):
    """A user-added exercise overlaid on the built-in routine."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    routine_type = db.Column(db.String(20), default='gym')
    section = db.Column(db.String(50))
    name = db.Column(db.String(100))
    sets = db.Column(db.Integer, default=3)
    reps = db.Column(db.String(20), default='8-12')
    weighted = db.Column(db.Boolean, default=True)
    equipment = db.Column(db.String(20), default='machine')
    description = db.Column(db.Text, default='')

    def to_dict(self):
        return {
            'name': self.name,
            'sets': str(self.sets),
            'reps': self.reps,
            'weighted': self.weighted,
            'equipment': self.equipment,
            'description': self.description or '',
            'custom': True,
        }


class HiddenExercise(db.Model):
    """A built-in exercise the user removed from their routine view."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    routine_type = db.Column(db.String(20), default='gym')
    exercise_name = db.Column(db.String(100))


def _fernet():
    """Symmetric cipher for stored user API keys.

    Prefers an explicit FERNET_KEY so SECRET_KEY can be rotated without
    bricking stored keys; falls back to deriving a key from SECRET_KEY for
    backward compatibility with existing deployments.
    """
    configured = current_app.config.get('FERNET_KEY')
    if configured:
        return Fernet(configured)
    digest = hashlib.sha256(current_app.config['SECRET_KEY'].encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class UserApiKey(db.Model):
    """A user's own LLM API key, stored encrypted. Overrides the server key."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    provider = db.Column(db.String(20), default='anthropic')
    encrypted_key = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)

    def set_key(self, raw_key):
        self.encrypted_key = _fernet().encrypt(raw_key.encode()).decode()

    def get_key(self):
        """Decrypt the stored key, or None if it can't be decrypted.

        Returns None when the cipher key changed (e.g. SECRET_KEY was rotated
        without a FERNET_KEY), so callers can prompt the user to re-enter it
        instead of crashing.
        """
        try:
            return _fernet().decrypt(self.encrypted_key.encode()).decode()
        except InvalidToken:
            return None

    def key_hint(self):
        """Last 4 characters, or None if the stored key can't be decrypted."""
        key = self.get_key()
        return key[-4:] if key else None


class GeneratedProgram(db.Model):
    """An AI-generated workout program. Draft until accepted on preview."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    name = db.Column(db.String(100))
    goal = db.Column(db.String(200))
    description = db.Column(db.Text, default='')
    program_json = db.Column(db.Text)  # {"Section": [gym-schema exercise dicts]}
    inputs_json = db.Column(db.Text)  # generation form inputs, kept for retries
    is_draft = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    @property
    def routine_key(self):
        return f'ai-{self.id}'

    def routine_data(self):
        return json.loads(self.program_json)

    def inputs(self):
        return json.loads(self.inputs_json) if self.inputs_json else {}


class UserProgression(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    exercise_category = db.Column(db.String(100))  # e.g., "Pull-up", "Squat"
    current_progression = db.Column(db.Integer)  # Index of current progression
    current_reps = db.Column(db.Integer, default=5)  # Current target reps
    last_updated = db.Column(db.DateTime, default=utc_now)


class RotationEntry(db.Model):
    """One step in the user's preferred workout rotation sequence."""

    __tablename__ = 'rotation_entry'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    routine_type = db.Column(db.String(50), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(100))


class WorkoutSchedule(db.Model):
    """A planned workout for a specific calendar date."""

    __tablename__ = 'workout_schedule'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    routine_type = db.Column(db.String(50), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'scheduled_date', name='uq_user_schedule_date'),
    )
