"""Loopback-only HTTP adapter for the lab, never an operational service client."""
import ipaddress
from urllib.parse import urlsplit

import requests

from .contracts import canonical
from .security import signed


class Rejected(Exception):
    """Definitive protocol/auth rejection; stop automatic delivery for investigation."""


class CoreTransport:
    def __init__(self, base_url, principal, *, timeout=(2, 5)):
        url = urlsplit(base_url)
        try:
            local = ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            local = False
        if not local or url.scheme != "http" or not url.port or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Laboratory transport requires an explicit loopback HTTP origin")
        self.url, self.principal, self.timeout = base_url.rstrip("/") + "/v2/stock/commands", principal, timeout
        self.session = requests.Session()
        self.session.trust_env = False  # No proxies, netrc or real service credentials.

    def __call__(self, command):
        body = canonical(command.payload())
        try:
            response = self.session.post(self.url, data=body,
                                         headers=signed(self.principal, "/v2/stock/commands", body),
                                         timeout=self.timeout, allow_redirects=False)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TimeoutError("Core outcome unknown") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise TimeoutError("Core outcome unknown")
        if response.status_code != 200:
            raise Rejected(f"Core HTTP {response.status_code}")
        # An incomplete response is also ambiguous. Only a receipt/event resolves it.
        try:
            return response.json()
        except ValueError as exc:
            raise TimeoutError("Core response unreadable") from exc

    def close(self):
        self.session.close()
