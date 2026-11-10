"""Required local run: fail missing/skipped PostgreSQL coverage and block Python egress."""
import ipaddress
import socket
import pytest

_original_connect = socket.socket.connect

def _local_connect(sock, address):
    if sock.family in {socket.AF_INET, socket.AF_INET6}:
        host = address[0]
        if host != "localhost":
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = False
            if not local:
                raise RuntimeError("J4.3A test runner refuses network egress")
    return _original_connect(sock, address)

@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    socket.socket.connect = _local_connect

@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    socket.socket.connect = _original_connect
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter and reporter.stats.get("skipped"):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
