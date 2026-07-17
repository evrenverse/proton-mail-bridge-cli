from __future__ import annotations

import contextlib
import ssl

from proton_mail_bridge.core import connection as conn
from proton_mail_bridge.core.config import Endpoint


def test_localhost_wins_when_reachable():
    ep = Endpoint()
    host, source = conn.resolve_host(ep, probe=lambda h, p, timeout=1.0: h == "127.0.0.1",
                                     is_wsl=lambda: True, read_cache=False, write_cache=False)
    assert host == "127.0.0.1"
    assert source == "localhost"


def test_wsl_falls_back_to_windows_host():
    ep = Endpoint()

    def probe(h, p, timeout=1.0):  # nur Windows-Host antwortet
        return h == "172.20.0.1"

    host, source = conn.resolve_host(
        ep, probe=probe, is_wsl=lambda: True,
        candidates=lambda: ["172.20.0.1"], read_cache=False, write_cache=False,
    )
    assert host == "172.20.0.1"
    assert source == "wsl-host"


def test_explicit_host_short_circuits():
    ep = Endpoint(host="example.test")
    host, source = conn.resolve_host(ep, probe=lambda *a, **k: False, is_wsl=lambda: False,
                                     read_cache=False, write_cache=False)
    assert host == "example.test"
    assert source == "explicit"


def test_unreachable_raises():
    from proton_mail_bridge.core.errors import ConnectionResolveError
    ep = Endpoint()
    try:
        conn.resolve_host(ep, probe=lambda *a, **k: False, is_wsl=lambda: False,
                          candidates=lambda: [], read_cache=False, write_cache=False)
        raise AssertionError("sollte werfen")
    except ConnectionResolveError:
        pass


def test_tls_context_is_unverified_by_default():
    ctx = conn.tls_context(Endpoint())
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE


def test_cache_roundtrip(tmp_path, monkeypatch):
    cache_file = tmp_path / "resolved.json"
    monkeypatch.setattr(conn, "cache_path", lambda: cache_file)
    conn._write_cache("1143:1025", "172.20.0.1")
    assert conn._read_cache("1143:1025") == "172.20.0.1"
    assert conn._read_cache("9999:9999") is None


def test_resolve_uses_cache_when_both_ports_ok(tmp_path, monkeypatch):
    cache_file = tmp_path / "resolved.json"
    monkeypatch.setattr(conn, "cache_path", lambda: cache_file)
    conn._write_cache("1143:1025", "172.20.0.1")
    host, source = conn.resolve_host(
        Endpoint(), probe=lambda h, p, timeout=1.0: h == "172.20.0.1",
        is_wsl=lambda: False, read_cache=True, write_cache=False)
    assert (host, source) == ("172.20.0.1", "cache")


class _FakeSock:
    def __init__(self, banner):
        self._banner = banner

    def settimeout(self, t):
        pass

    def recv(self, n):
        if self._banner is None:
            raise TimeoutError("timed out")
        return self._banner


def _fake_connect(banner):
    @contextlib.contextmanager
    def connect(addr, timeout=None):
        yield _FakeSock(banner)
    return connect


def test_detect_security_plaintext_banner_is_starttls():
    assert conn.detect_security("h", 1025, connect=_fake_connect(b"220 bridge")) == "starttls"
    assert conn.detect_security("h", 1143, connect=_fake_connect(b"* OK")) == "starttls"


def test_detect_security_silence_is_ssl():
    # a TLS server waits for the ClientHello → no plaintext banner (macOS bridge SMTP)
    assert conn.detect_security("h", 1025, connect=_fake_connect(None)) == "ssl"


def test_detect_security_unreachable_is_none():
    @contextlib.contextmanager
    def refused(addr, timeout=None):
        raise OSError("refused")
        yield
    assert conn.detect_security("h", 1025, connect=refused) is None
