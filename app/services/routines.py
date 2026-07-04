"""Resolving routine keys to human labels and a user's saved AI programs."""

from app.models import GeneratedProgram


def active_ai_programs(user):
    """The user's saved (non-draft) AI programs, oldest first."""
    return (
        GeneratedProgram.query.filter_by(user_id=user.id, is_draft=False)
        .order_by(GeneratedProgram.created_at)
        .all()
    )


def routine_display_name(routine_type, ai_programs):
    """Human-readable label for a routine_type ('bwf', 'gym', or 'ai-<id>')."""
    if routine_type == 'bwf':
        return 'BWF'
    if routine_type == 'gym':
        return 'Gym'
    for program in ai_programs:
        if program.routine_key == routine_type:
            return program.name
    return routine_type
