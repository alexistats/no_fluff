"""PWA plumbing: service worker, offline page, manifest."""

import json


def test_service_worker_served_at_root_with_scope_header(client):
    resp = client.get('/sw.js')
    assert resp.status_code == 200
    assert resp.headers['Service-Worker-Allowed'] == '/'
    assert 'javascript' in resp.headers['Content-Type']
    assert b'addEventListener' in resp.data


def test_offline_page_renders_without_login(client):
    resp = client.get('/offline')
    assert resp.status_code == 200
    assert b'offline' in resp.data.lower()


def test_manifest_is_valid_and_served(client):
    resp = client.get('/static/manifest.json')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['start_url'] == '/'
    assert data['display'] == 'standalone'
    assert any(icon['purpose'] == 'maskable' for icon in data['icons'])


def test_base_page_links_manifest_and_sw(client):
    resp = client.get('/login')
    assert b'rel="manifest"' in resp.data
    assert b'apple-touch-icon' in resp.data
