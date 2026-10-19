import re
import struct
from pathlib import Path
from fastapi.testclient import TestClient
from app.online_main import app

ROOT = Path('app/merchant_pwa')


def test_manifest_and_all_precached_assets():
    client = TestClient(app)
    manifest = client.get('/merchant/manifest.webmanifest')
    assert manifest.status_code == 200
    data = manifest.json()
    assert data['start_url'] == '/merchant' and data['display'] == 'standalone'
    for icon in data['icons']:
        response = client.get(icon['src']); assert response.status_code == 200
        width,height = struct.unpack('!II', response.content[16:24])
        assert f'{width}x{height}' == icon['sizes']
    worker = client.get('/merchant/service-worker.js')
    assert worker.status_code == 200
    assert worker.headers['service-worker-allowed'] == '/merchant'
    paths = re.findall(r"'(/merchant/[^']+)'", worker.text.split('self.addEventListener')[0])
    for path in paths:
        assert client.get(path).status_code == 200, path


def test_cache_is_static_allowlist_and_no_business_storage():
    worker = (ROOT/'service-worker.js').read_text()
    assert 'STATIC.includes(url.pathname)' in worker
    assert 'cache.put' not in re.sub(r'//[^\n]*', '', worker)
    assert "url.pathname.startsWith('/merchant-api/')" in worker
    assert "url.pathname.startsWith('/online-admin/')" in worker
    assert "url.pathname.startsWith('/shop/')" in worker
    assert '!url.search' in worker
    assert "self.addEventListener('push'" in worker
    assert "self.addEventListener('notificationclick'" in worker
    source = '\n'.join(p.read_text() for p in ROOT.rglob('*') if p.suffix in ('.js','.html','.css'))
    for forbidden in ('ADMIN_TOKEN','Merchant ID','localStorage','sessionStorage','VAPID_PRIVATE','RAILWAY_TOKEN'):
        assert forbidden not in source
    assert 'innerHTML' not in source


def test_asset_traversal_denied():
    response = TestClient(app).get('/merchant/assets/%2e%2e/online_main.py')
    assert response.status_code == 404
