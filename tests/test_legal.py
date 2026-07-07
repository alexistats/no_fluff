"""Legal pages, the AI safety disclaimer, and the prompt guardrail."""

import json
import re

from app import db
from app.ai_generator import SYSTEM_PROMPT
from app.models import GeneratedProgram, User


def _text(resp):
    """Response body with whitespace collapsed, so phrase checks don't depend
    on how the template happens to wrap lines."""
    return re.sub(r'\s+', ' ', resp.get_data(as_text=True))


# ── Public legal pages ─────────────────────────────────────────────


def test_terms_page_is_public_and_complete(client):
    resp = client.get('/terms')
    assert resp.status_code == 200
    text = _text(resp)
    assert 'Terms of Service' in text
    assert '16 years old' in text  # age gate
    assert 'at your own risk' in text  # health/liability
    assert 'not professional fitness or medical advice' in text


def test_privacy_page_is_public_and_complete(client):
    resp = client.get('/privacy')
    assert resp.status_code == 200
    text = _text(resp)
    assert 'Privacy Policy' in text
    assert "don't sell your data" in text
    assert 'PIPEDA' in text
    assert 'Anthropic' in text  # AI sub-processor named


def test_contact_email_shows_when_configured(client, app):
    app.config['LEGAL_CONTACT_EMAIL'] = 'privacy@example.com'
    assert b'privacy@example.com' in client.get('/terms').data
    assert b'privacy@example.com' in client.get('/privacy').data


def test_contact_email_falls_back_when_unset(client, app):
    app.config['LEGAL_CONTACT_EMAIL'] = None
    # No crash, and a sensible fallback phrase instead of a broken mailto.
    resp = client.get('/privacy')
    assert resp.status_code == 200
    assert b'published on the app' in resp.data


# ── Links into the legal pages ─────────────────────────────────────


def test_register_page_links_terms_and_age_gate(client):
    body = client.get('/register').data
    assert b'/terms' in body
    assert b'/privacy' in body
    assert b'16 or older' in body


def test_footer_links_present(client):
    body = client.get('/login').data
    assert b'/terms' in body
    assert b'/privacy' in body


# ── AI safety disclaimer ───────────────────────────────────────────


def test_generate_page_shows_ai_disclaimer(logged_in_client):
    text = _text(logged_in_client.get('/generate'))
    assert 'not professional fitness or medical advice' in text
    assert 'train at your own risk' in text


def test_preview_page_shows_ai_disclaimer(logged_in_client, app):
    with app.app_context():
        user = User.query.first()
        program = GeneratedProgram(
            user_id=user.id,
            name='Test Program',
            goal='climbing',
            description='A test.',
            program_json=json.dumps({'Day 1': []}),
            inputs_json=json.dumps({}),
            is_draft=True,
        )
        db.session.add(program)
        db.session.commit()
        program_id = program.id

    text = _text(logged_in_client.get(f'/generate/preview/{program_id}'))
    assert 'not professional fitness or medical advice' in text


# ── AI prompt guardrail ────────────────────────────────────────────


def test_system_prompt_has_safety_guardrails():
    assert 'Safety' in SYSTEM_PROMPT
    assert 'one-rep-max' in SYSTEM_PROMPT
    assert 'injuries' in SYSTEM_PROMPT
