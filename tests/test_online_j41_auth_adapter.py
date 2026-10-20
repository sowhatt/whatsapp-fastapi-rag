"""Audit regression only: unsupported Auth V2 proofs must NOT grant access.

These cases intentionally do not claim a working Auth V2 business session.
The audited authority has no compatible cookie/handoff yet.
"""
import pytest
from fastapi.testclient import TestClient
from app.online_main import app


@pytest.mark.parametrize('headers', [
    {},
    {'Cookie': '__Host-whatzabi-enrollment=unsupported-test-proof'},
    {'Cookie': '__Host-whatzabi-passkey-login=unsupported-test-proof'},
    {'Cookie': '__Host-whatzabi-access-request=unsupported-test-proof'},
    {'Authorization': 'Bearer unsupported-test-proof'},
    {'x-merchant-id': '1'},
    {'x-tenant-id': '1'},
    {'x-admin-token': 'unsupported-test-proof'},
])
def test_no_source_proof_is_promoted_to_business_session(headers):
    client = TestClient(app)
    try:
        response = client.get('/merchant-api/bootstrap', headers=headers)
        assert response.status_code == 401
        assert response.json() == {'detail': 'Connexion commerçant requise.'}
        assert response.headers['cache-control'] == 'no-store, private'
        assert 'set-cookie' not in response.headers
    finally:
        client.close()
