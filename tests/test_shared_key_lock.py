"""Phase 6: the shared-API-key access lock."""

from app.ai_generator import resolve_api_key
from app.models import User


def _resolve(app):
    with app.app_context():
        return resolve_api_key(User.query.first())


def _unlock(client, code):
    return client.post('/settings/unlock_ai', data={'access_code': code}, follow_redirects=True)


def test_no_code_configured_keeps_shared_key_open(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE=None)
    assert _resolve(app) == 'sk-server'


def test_configured_code_locks_the_shared_key(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE='letmein')
    assert _resolve(app) is None


def test_locked_user_is_sent_to_settings_from_generate(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE='letmein')
    resp = logged_in_client.post('/generate', data={'goal': 'climbing'}, follow_redirects=True)
    assert b'unlock shared access or add your own key' in resp.data


def test_wrong_code_stays_locked(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE='letmein')
    resp = _unlock(logged_in_client, 'wrong')
    assert b'not recognized' in resp.data
    assert _resolve(app) is None


def test_right_code_unlocks_permanently(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE='letmein')

    resp = _unlock(logged_in_client, 'letmein')

    assert b'Shared AI access unlocked' in resp.data
    assert _resolve(app) == 'sk-server'
    with app.app_context():
        assert User.query.first().shared_key_unlocked_at is not None
    assert b'\xe2\x9c\x93 Unlocked' in logged_in_client.get('/settings').data


def test_unlock_route_disabled_without_config(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY=None, SHARED_KEY_ACCESS_CODE=None)
    resp = _unlock(logged_in_client, 'anything')
    assert b'not enabled on this server' in resp.data


def test_own_key_bypasses_the_lock(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE='letmein')
    logged_in_client.post('/settings', data={'api_key': 'sk-ant-my-own-key'})
    assert _resolve(app) == 'sk-ant-my-own-key'


def test_settings_shows_unlock_form_only_when_locked(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE='letmein')
    page = logged_in_client.get('/settings').data
    assert b'Shared AI access' in page and b'name="access_code"' in page

    # No code configured: the section disappears entirely.
    app.config.update(SHARED_KEY_ACCESS_CODE=None)
    page = logged_in_client.get('/settings').data
    assert b'Shared AI access' not in page


def test_generate_page_reflects_locked_state(logged_in_client, app):
    app.config.update(ANTHROPIC_API_KEY='sk-server', SHARED_KEY_ACCESS_CODE='letmein')
    page = logged_in_client.get('/generate').data
    assert b'Unlock shared access or add your own key' in page

    _unlock(logged_in_client, 'letmein')
    page = logged_in_client.get('/generate').data
    assert b'Unlock shared access or add your own key' not in page
