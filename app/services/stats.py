"""Read-side aggregation for the activity dashboard.

Everything here is a bounded SQL query — no loading a user's whole workout
history into Python, and no per-exercise query loop for weight trends.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import func

from app import db
from app.models import ExerciseLog, Workout
from app.services.routines import routine_display_name

LBS_TO_KG = 0.453592


def _count(user_id, *filters):
    return (
        db.session.query(func.count(Workout.id))
        .filter(Workout.user_id == user_id, *filters)
        .scalar()
        or 0
    )


def workout_counts(user_id, today):
    """Total / this-week / this-month workout counts.

    `today` is a UTC date; Workout.date is stored in UTC, so a midnight
    boundary datetime compares the same as the original `w.date.date()` logic.
    """
    week_start = datetime.combine(today - timedelta(days=today.weekday()), time.min)
    month_start = datetime.combine(today.replace(day=1), time.min)
    return {
        'total': _count(user_id),
        'this_week': _count(user_id, Workout.date >= week_start),
        'this_month': _count(user_id, Workout.date >= month_start),
    }


def weekly_frequency(user_id, today, weeks=12):
    """(labels, values) of workout counts per ISO week for the last `weeks`."""
    start = datetime.combine(today - timedelta(weeks=weeks), time.min)
    rows = (
        db.session.query(Workout.date)
        .filter(Workout.user_id == user_id, Workout.date >= start)
        .all()
    )
    freq = {}
    for (workout_date,) in rows:
        iso = workout_date.date().isocalendar()
        freq[(iso[0], iso[1])] = freq.get((iso[0], iso[1]), 0) + 1

    labels, values = [], []
    for i in range(weeks - 1, -1, -1):
        iso = (today - timedelta(weeks=i)).isocalendar()
        labels.append(f'W{iso[1]}')
        values.append(freq.get((iso[0], iso[1]), 0))
    return labels, values


def routine_breakdown(user_id, ai_programs):
    """[{label, count}] per routine_type, most-used first."""
    rows = (
        db.session.query(Workout.routine_type, func.count(Workout.id))
        .filter(Workout.user_id == user_id)
        .group_by(Workout.routine_type)
        .all()
    )
    ordered = sorted(rows, key=lambda row: (-row[1], row[0]))
    return [
        {'label': routine_display_name(rt, ai_programs), 'count': count} for rt, count in ordered
    ]


def top_exercises(user_id, limit=10):
    """[{name, count}] of the most-logged exercises."""
    rows = (
        db.session.query(ExerciseLog.exercise_name, func.count(ExerciseLog.id))
        .join(Workout)
        .filter(Workout.user_id == user_id)
        .group_by(ExerciseLog.exercise_name)
        .order_by(func.count(ExerciseLog.id).desc())
        .limit(limit)
        .all()
    )
    return [{'name': name, 'count': count} for name, count in rows]


def _max_weight_kg(weight_str, unit):
    try:
        weights = [float(w) for w in weight_str.split(',') if w and w != '0']
    except (ValueError, AttributeError):
        return None
    if not weights:
        return None
    top = max(weights)
    return round(top * LBS_TO_KG, 1) if unit == 'lbs' else top


def weight_trends(user_id, limit=5):
    """{exercise_name: [{date, weight(kg)}]} for the top `limit` weighted lifts.

    Two queries total (top-N names, then one IN query for their logs) — no
    per-exercise loop.
    """
    top = (
        db.session.query(ExerciseLog.exercise_name, func.count(ExerciseLog.id))
        .join(Workout)
        .filter(Workout.user_id == user_id, ExerciseLog.weight_per_set.isnot(None))
        .group_by(ExerciseLog.exercise_name)
        .order_by(func.count(ExerciseLog.id).desc())
        .limit(limit)
        .all()
    )
    names = [name for name, _ in top]
    if not names:
        return {}

    rows = (
        db.session.query(
            ExerciseLog.exercise_name,
            Workout.date,
            ExerciseLog.weight_per_set,
            ExerciseLog.weight_unit,
        )
        .join(Workout, ExerciseLog.workout_id == Workout.id)
        .filter(
            Workout.user_id == user_id,
            ExerciseLog.exercise_name.in_(names),
            ExerciseLog.weight_per_set.isnot(None),
        )
        .order_by(Workout.date)
        .all()
    )
    trends = {}
    for name, workout_date, weight_str, unit in rows:
        max_kg = _max_weight_kg(weight_str, unit)
        if max_kg is None:
            continue
        trends.setdefault(name, []).append(
            {'date': workout_date.strftime('%Y-%m-%d'), 'weight': max_kg}
        )
    # Preserve the top-N ordering, dropping any that had no chartable points.
    return {name: trends[name] for name in names if name in trends}
