"""Claude-powered workout program generation.

Builds a personalized program (goal, equipment, availability) in the same
JSON shape as data/gym_routine.json so generated programs get all existing
features: per-set logging, rest timers, last-session prefill, customization.
"""

import json

import anthropic
from flask import current_app

from app.models import UserApiKey

MODEL = 'claude-opus-4-8'
ALLOWED_EQUIPMENT = ('barbell', 'dumbbell', 'machine', 'bodyweight')
MAX_SECTIONS = 7
MAX_EXERCISES_PER_SECTION = 12
MAX_SETS = 5

PROGRAM_SCHEMA = {
    'type': 'object',
    'properties': {
        'program_name': {'type': 'string'},
        'description': {'type': 'string'},
        'sections': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'exercises': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string'},
                                'sets': {'type': 'string', 'enum': ['1', '2', '3', '4', '5']},
                                'reps': {'type': 'string'},
                                'weighted': {'type': 'boolean'},
                                'equipment': {'type': 'string', 'enum': list(ALLOWED_EQUIPMENT)},
                                'description': {'type': 'string'},
                            },
                            'required': [
                                'name',
                                'sets',
                                'reps',
                                'weighted',
                                'equipment',
                                'description',
                            ],
                            'additionalProperties': False,
                        },
                    },
                },
                'required': ['name', 'exercises'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['program_name', 'description', 'sections'],
    'additionalProperties': False,
}

SYSTEM_PROMPT = """You are an expert strength and conditioning coach. You design \
safe, effective, evidence-based workout programs tailored to a person's goal \
(e.g. climbing, a 5k run, ringette, general strength), the equipment they have \
access to, and how many days per week they can train.

Rules for the program you output:
- Create exactly one section per training day, named like "Day 1 – Pull & Core" \
so the focus is clear. Order exercises as they should be performed.
- Start each day with 1-3 warm-up exercises appropriate to that day's work \
(low sets, e.g. sets "1"-"2").
- Only use equipment from the person's list. "bodyweight" is always available. \
Mark weighted=false and equipment="bodyweight" for unloaded exercises.
- reps is a short string like "8-12", "5", or "30-60s" for timed holds.
- Fit the session to the requested length: roughly 4-5 working exercises for \
45 min, 6-8 for 75-90 min, plus warm-ups.
- Exercise names must be unique across the whole program, specific, and stable \
(they key the user's logging history). Prefer conventional names.
- description is 1-2 sentences of form cues or intent for that exercise.
- Match volume and intensity to the person's experience level, and bias \
exercise selection toward the stated goal (e.g. grip/pull work for climbing, \
posterior chain and intervals support for running)."""

GENERATION_ERROR_HINTS = {
    # APITimeoutError subclasses APIConnectionError — keep it first
    anthropic.APITimeoutError: 'The coach took too long to respond. Try again — it usually works '
    'on the second attempt.',
    anthropic.AuthenticationError: 'The Claude API key was rejected. Check it in Settings.',
    anthropic.PermissionDeniedError: 'The Claude API key does not have permission '
    'for this request.',
    anthropic.RateLimitError: 'The Claude API is rate-limiting requests right now. '
    'Try again in a minute.',
    anthropic.APIConnectionError: 'Could not reach the Claude API. '
    'Check your connection and try again.',
}


class GenerationError(Exception):
    """Raised with a user-facing message when generation fails."""


def resolve_api_key(user):
    """User's stored key if present and decryptable, else the server key, else None."""
    record = UserApiKey.query.filter_by(user_id=user.id, provider='anthropic').first()
    if record:
        key = record.get_key()
        if key:
            return key
        # Stored key is undecryptable (e.g. SECRET_KEY rotated) — fall back to
        # the server key rather than failing outright.
    return current_app.config.get('ANTHROPIC_API_KEY')


def describe_inputs(inputs):
    """Render the generation form inputs as the user-turn prompt."""
    equipment = ', '.join(inputs.get('equipment', [])) or 'bodyweight only'
    lines = [
        f'Goal: {inputs["goal"]}',
        f'Available equipment: {equipment}',
        f'Training days per week: {inputs["days_per_week"]}',
        f'Time per session: about {inputs["session_length"]} minutes',
        f'Experience level: {inputs["experience"]}',
    ]
    if inputs.get('notes'):
        lines.append(f'Other notes: {inputs["notes"]}')
    lines.append('Design my workout program.')
    return '\n'.join(lines)


def _get_completion(client, messages):
    """One Claude call. Factored out so tests can stub the transport."""
    return client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={'type': 'adaptive'},
        system=SYSTEM_PROMPT,
        messages=messages,
        output_config={
            # medium effort keeps generation fast enough for a synchronous
            # web request without hurting program quality
            'effort': 'medium',
            'format': {'type': 'json_schema', 'schema': PROGRAM_SCHEMA},
        },
    )


def generate_program(api_key, inputs, previous_program=None, feedback=None):
    """Call Claude and return a validated (name, description, routine) tuple.

    routine is {"Section name": [exercise dicts]} — the gym_routine.json shape.
    Raises GenerationError with a user-facing message on failure.
    """
    messages = [{'role': 'user', 'content': describe_inputs(inputs)}]
    if previous_program is not None and feedback:
        messages.append({'role': 'assistant', 'content': json.dumps(previous_program)})
        messages.append(
            {
                'role': 'user',
                'content': f'Revise the program with this feedback: {feedback}\n'
                "Keep everything that wasn't criticized.",
            }
        )

    # Fail with a friendly message well before gunicorn's worker timeout
    # (--timeout 300) would kill the request mid-flight.
    client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=1)
    last_error = None
    for _ in range(2):  # one automatic retry on invalid output
        try:
            message = _get_completion(client, messages)
        except anthropic.APIError as exc:
            current_app.logger.exception('Claude API error during program generation')
            for exc_type, hint in GENERATION_ERROR_HINTS.items():
                if isinstance(exc, exc_type):
                    raise GenerationError(hint) from exc
            raise GenerationError('The Claude API returned an error. Try again shortly.') from exc

        if message.stop_reason == 'max_tokens':
            raise GenerationError(
                'The program was too long to finish. Try fewer training days or a '
                'shorter session length.'
            )
        if message.stop_reason == 'refusal':
            current_app.logger.warning('Claude refused the generation request')
            raise GenerationError(
                'The coach declined to answer that request. Try rephrasing your goal.'
            )

        text = next((b.text for b in message.content if b.type == 'text'), '')
        try:
            data = json.loads(text)
            return validate_program(data)
        except (ValueError, KeyError, TypeError) as exc:
            last_error = exc
            if text:
                # Tell the model its previous output was rejected so the retry
                # isn't an identical request.
                messages = messages + [
                    {'role': 'assistant', 'content': text},
                    {
                        'role': 'user',
                        'content': f'That response was not valid for the required schema ({exc}). '
                        'Return only a corrected JSON program.',
                    },
                ]

    current_app.logger.error('Claude returned an invalid program twice: %s', last_error)
    raise GenerationError(
        'Claude returned an invalid program twice in a row. Try again or rephrase your goal.'
    ) from last_error


def validate_program(data):
    """Check a generated program and convert it to the stored routine shape."""
    sections = data['sections']
    if not 1 <= len(sections) <= MAX_SECTIONS:
        raise ValueError(f'expected 1-{MAX_SECTIONS} sections, got {len(sections)}')

    routine = {}
    seen_names = set()
    for section in sections:
        section_name = section['name'].strip()
        if not section_name or section_name in routine:
            raise ValueError(f'invalid or duplicate section name: {section_name!r}')
        exercises = section['exercises']
        if not 1 <= len(exercises) <= MAX_EXERCISES_PER_SECTION:
            raise ValueError(f'section {section_name!r} has {len(exercises)} exercises')

        cleaned = []
        for ex in exercises:
            name = ex['name'].strip()
            if not name or name.lower() in seen_names:
                raise ValueError(f'invalid or duplicate exercise name: {name!r}')
            seen_names.add(name.lower())
            if not 1 <= int(ex['sets']) <= MAX_SETS:
                raise ValueError(f'{name!r}: sets out of range')
            if ex['equipment'] not in ALLOWED_EQUIPMENT:
                raise ValueError(f'{name!r}: bad equipment {ex["equipment"]!r}')
            if not ex['reps'].strip():
                raise ValueError(f'{name!r}: empty reps')
            cleaned.append(
                {
                    'name': name[:100],
                    'sets': ex['sets'],
                    'reps': ex['reps'].strip()[:20],
                    'weighted': bool(ex['weighted']),
                    'equipment': ex['equipment'],
                    'description': ex['description'].strip(),
                }
            )
        routine[section_name[:50]] = cleaned

    name = data['program_name'].strip()[:100] or 'AI Program'
    return name, data['description'].strip(), routine
