import hashlib
import hmac
import json
import os
import tempfile

fd, path = tempfile.mkstemp(suffix='.db')
os.close(fd)
os.environ['DATABASE_URL'] = 'sqlite:///' + path
os.environ['API_KEY'] = 'test-key'
os.environ['WEBHOOK_SECRET'] = 'test-secret'

from fastapi.testclient import TestClient
from app.main import app


def test_auth_and_idempotency():
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/api/integrations').status_code == 401
        headers = {'X-API-Key': 'test-key', 'Idempotency-Key': 'create-1'}
        payload = {'name': 'Alex', 'email': 'alex@example.com'}
        first = client.post('/api/customers', json=payload, headers=headers)
        assert first.status_code == 201, first.text
        second = client.post('/api/customers', json=payload, headers=headers)
        assert second.json()['id'] == first.json()['id']
        conflict = client.post('/api/customers', json={'name': 'Other', 'email': 'other@example.com'}, headers=headers)
        assert conflict.status_code == 409
        assert client.get('/api/integrations', headers=headers).json()[0]['status'] == 'pending'


def test_signed_webhook_deduplication():
    with TestClient(app) as client:
        raw = json.dumps({'event_id': 'evt-1', 'kind': 'updated'}).encode()
        sig = hmac.new(b'test-secret', raw, hashlib.sha256).hexdigest()
        headers = {'X-API-Key': 'test-key', 'X-Webhook-Signature': sig, 'Content-Type': 'application/json'}
        assert client.post('/api/webhooks/partner', content=raw).status_code == 401
        assert client.post('/api/webhooks/partner', content=raw, headers=headers).json()['status'] == 'accepted'
        assert client.post('/api/webhooks/partner', content=raw, headers=headers).json()['status'] == 'duplicate'
