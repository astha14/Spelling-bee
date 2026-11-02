from fastapi.testclient import TestClient
from backend.main import app
from backend import config

def test_page_and_health():
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/app.js').status_code == 200
        assert client.get('/api/health').json()['ok']

def test_missing_credentials(monkeypatch):
    monkeypatch.setattr(config, 'CARTESIA_API_KEY', '')
    with TestClient(app) as client:
        response = client.post('/api/offer', json={'sdp': 'dummy', 'type': 'offer'})
        assert response.status_code == 503
        assert 'CARTESIA_API_KEY' in response.json()['detail']

def test_invalid_offer():
    with TestClient(app) as client:
        assert client.post('/api/offer', json={'sdp':'x', 'type':'offer', 'difficulty':'unknown'}).status_code == 400
        assert client.post('/api/offer', json={}).status_code == 422


def test_frontend_assets_are_not_cached():
    with TestClient(app) as client:
        for path in ('/', '/index.html', '/app.js?v=voice-fixes-2', '/style.css'):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
