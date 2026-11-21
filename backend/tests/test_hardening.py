"""Security and event-day reliability regression checks.

These run against the existing isolated ClickBook test DB on CI.
"""
from fastapi.testclient import TestClient
import pytest

from app.limits import check_rate, clear_for_tests
from app import main


def test_email_login_throttling():
    client = TestClient(main.app)
    payload = {'email': 'nonexistent-credential-probe@example.com', 'password': 'bad-password-123'}
    for attempt in range(12):
        assert client.post('/api/auth/login', json=payload).status_code == 401
    blocked = client.post('/api/auth/login', json=payload)
    assert blocked.status_code == 429
    assert blocked.headers['retry-after'] == '600'
    # A different email must not be permanently locked out by this bucket.
    other = dict(payload, email='other-credential-probe@example.com')
    assert client.post('/api/auth/login', json=other).status_code == 401


def test_limiter_is_bounded_and_denies_overuse():
    clear_for_tests()
    for _ in range(2):
        check_rate('check', 'test-user', limit=2, period=60)
    with pytest.raises(Exception) as exc:
        check_rate('check', 'test-user', limit=2, period=60)
    assert getattr(exc.value, 'status_code', None) == 429
    clear_for_tests()


def test_security_headers_are_sent_on_api_and_error_responses(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main, 'IS_PRODUCTION', True)
    for path in ('/api/health', '/api/g/invalid-guest-link'):
        response = client.get(path)
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['referrer-policy'] == 'no-referrer'
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['content-security-policy'].startswith("default-src 'self'")
    resp = client.get('/api/g/invalid-guest-link')
    assert resp.headers['cache-control'] == 'private, no-store'


def test_sse_uses_same_snapshot_within_short_window():
    client = TestClient(main.app)
    signup = client.post('/api/auth/register', json={
        'email': 'sse-security-check@example.com',
        'password': 'a-good-unique-password-123'
    })
    assert signup.status_code == 201
    token = signup.json()['token']
    event = client.post('/api/events',
                        headers={'Authorization': 'Bearer ' + token},
                        json={'title': 'Event snapshot check'}).json()
    code = event['guest_code']
    with main._sse_cache_lock:
        main._sse_state_cache.pop(code, None)
    first = main.guest_event_state(code)
    second = main.guest_event_state(code)
    assert first is second  # No second database query needed within TTL.
    assert first['count'] == 0
    assert first['processed'] == 0
