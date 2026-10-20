"""Static boundaries remain valid while the Auth V2 handoff is unavailable."""
import ast
import re
from pathlib import Path


ROOT = Path('app/merchant_pwa')


def test_frontend_never_stores_session_or_imports_shop_auth():
    source = '\n'.join(p.read_text() for p in ROOT.rglob('*') if p.suffix in {'.js', '.html'})
    for forbidden in ('localStorage', 'sessionStorage', 'indexedDB', 'access_token', 'Authorization', 'document.cookie'):
        assert forbidden not in source
    tree = ast.parse(Path('app/merchant/identity.py').read_text())
    modules = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(module.startswith(('app.auth', 'app.routers.auth', 'app.services.quick_auth')) for module in modules)


def test_service_worker_only_caches_static_shell_not_auth():
    source = (ROOT / 'service-worker.js').read_text()
    precache = source.split("self.addEventListener('install'")[0]
    paths = re.findall(r"'(/[^']+)'", precache)
    assert paths
    assert all(path.startswith('/merchant/assets/') or path == '/merchant/manifest.webmanifest' for path in paths)
    for route in ('/merchant/session', '/merchant/login', '/merchant/logout', '/merchant/auth/callback', '/auth/app'):
        assert route not in paths
    assert 'STATIC.includes(url.pathname)' in source
    assert 'cache.put(' not in source
    assert "event.request.method !== 'GET'" in source
