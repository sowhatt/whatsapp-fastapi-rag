"""Fail-closed endpoint policy and a DNS-pinned, non-redirecting Push transport."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import re
import socket
import ssl
from urllib.parse import urlsplit

import requests
import urllib3


class InvalidPushEndpoint(ValueError):
    def __init__(self):
        # Never include an endpoint, subscription token, DNS answer or credentials.
        super().__init__("Endpoint Web Push non autorisé.")


_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_LOCAL_SUFFIXES = ("localhost", "local", "internal", "home.arpa")


def _matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def _domain(host: str) -> bool:
    return len(host) <= 253 and all(_LABEL.fullmatch(p) for p in host.split("."))


def allowed_host_suffixes() -> tuple[str, ...]:
    """Require explicit provider domains in every environment, including staging."""
    values = tuple(
        value.strip().lower()
        for value in os.getenv("WEB_PUSH_ALLOWED_HOST_SUFFIXES", "").split(",")
    )
    for value in values:
        if (
            not _domain(value)
            or "." not in value
            or any(_matches(value, suffix) for suffix in _LOCAL_SUFFIXES)
        ):
            raise InvalidPushEndpoint()
        try:
            ipaddress.ip_address(value)
        except ValueError:
            continue
        raise InvalidPushEndpoint()
    return values


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not address.is_global or any((
        address.is_loopback, address.is_private, address.is_link_local,
        address.is_multicast, address.is_reserved, address.is_unspecified,
    )):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # Reject scoped and transition addresses (mapped IPv4, NAT64, 6to4,
        # Teredo), whose effective destination can differ from the outer IP.
        return (
            address.scope_id is None
            and address in ipaddress.ip_network("2000::/3")
            and address.sixtofour is None
            and address.teredo is None
        )
    return True


@dataclass(frozen=True)
class PushEndpoint:
    url: str
    hostname: str
    addresses: tuple[str, ...]


def validate_push_endpoint(endpoint: object) -> PushEndpoint:
    """Resolve all addresses; reject the entire subscription if any is unsafe."""
    if (
        not isinstance(endpoint, str)
        or not endpoint
        or len(endpoint) > 8192
        or any(ord(c) <= 32 or ord(c) >= 127 for c in endpoint)
        or "\\" in endpoint
    ):
        raise InvalidPushEndpoint()
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.netloc.endswith(":")
            or parsed.fragment
            or not _domain(host)
            or any(_matches(host, suffix) for suffix in _LOCAL_SUFFIXES)
        ):
            raise InvalidPushEndpoint()
        if not any(_matches(host, suffix) for suffix in allowed_host_suffixes()):
            raise InvalidPushEndpoint()
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = tuple(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses or not all(_public_address(ip) for ip in addresses):
            raise InvalidPushEndpoint()
    except (ValueError, OSError, UnicodeError):
        raise InvalidPushEndpoint() from None
    return PushEndpoint(endpoint, host, addresses)


class PinnedPushSession(requests.Session):
    """Minimal pywebpush POST transport; no proxies, redirects or second host DNS.

    Connect to a validated numeric IP while checking the original hostname in
    TLS (SNI + certificate) and sending it in Host. A provider failure is final
    for this best-effort attempt; no automatic retry can change destination.
    """

    def __init__(self, endpoint: str):
        super().__init__()
        self.trust_env = False
        self.target = validate_push_endpoint(endpoint)

    def post(self, url, data=None, headers=None, timeout=None, **kwargs):
        if url != self.target.url or kwargs:
            raise InvalidPushEndpoint()
        prepared = requests.Request("POST", url, data=data, headers=headers).prepare()
        prepared.headers["Host"] = self.target.hostname
        with urllib3.HTTPSConnectionPool(
            host=self.target.addresses[0],
            port=443,
            server_hostname=self.target.hostname,
            assert_hostname=self.target.hostname,
            cert_reqs=ssl.CERT_REQUIRED,
            ca_certs=requests.certs.where(),
            timeout=urllib3.Timeout(connect=5, read=10),
            retries=False,
        ) as pool:
            response = pool.urlopen(
                "POST", prepared.path_url,
                body=prepared.body, headers=prepared.headers,
                redirect=False, retries=False, preload_content=False,
            )
            try:
                # Bound provider response memory; its body is not needed by us.
                content = response.read(4096)
            finally:
                response.close()
            result = requests.Response()
            result.status_code = response.status
            result.reason = response.reason
            result.headers.update(response.headers)
            result._content = content
            result.url = url
            return result
