from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from proton_mail_bridge.core.config import Endpoint
from proton_mail_bridge.core.errors import ConnectionResolveError

_CACHE_TTL = 600  # seconds


def detect_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def windows_host_candidates() -> list[str]:
    """NAT mode: default gateway + resolv.conf nameservers as Windows host candidates."""
    candidates: list[str] = []
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True, text=True, timeout=2
        )
        for line in out.stdout.splitlines():
            parts = line.split()
            if "via" in parts:
                candidates.append(parts[parts.index("via") + 1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            if line.startswith("nameserver"):
                ip = line.split()[1]
                if ip not in candidates:
                    candidates.append(ip)
    except OSError:
        pass
    return candidates


def detect_security(
    host: str, port: int, timeout: float = 2.0,
    connect: Callable[..., Any] = socket.create_connection,
) -> str | None:
    """Banner probe: a plaintext banner (SMTP `220 …` / IMAP `* OK`) → "starttls";
    connection accepted but silent → TLS-first server (in TLS the client speaks first)
    → "ssl". Unreachable/unclear → None. macOS Bridge: SMTP often ssl, IMAP starttls."""
    try:
        with connect((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                data = sock.recv(64)
            except TimeoutError:
                return "ssl"
            return "starttls" if data else None
    except OSError:
        return None


def probe(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def cache_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "proton-mail-bridge" / "resolved-host.json"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "proton-mail-bridge" / "resolved-host.json"


def _read_cache(key: str) -> str | None:
    try:
        data = json.loads(cache_path().read_text())
        entry = data.get(key)
        if entry and time.time() - entry["ts"] < _CACHE_TTL:
            return entry["host"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def _write_cache(key: str, host: str) -> None:
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        data[key] = {"host": host, "ts": int(time.time())}
        path.write_text(json.dumps(data))
    except (OSError, ValueError):
        pass


def resolve_host(
    endpoint: Endpoint,
    *,
    probe: Callable[..., bool] = probe,
    is_wsl: Callable[[], bool] = detect_wsl,
    candidates: Callable[[], list[str]] = windows_host_candidates,
    read_cache: bool = True,
    write_cache: bool = True,
) -> tuple[str, str]:
    """Returns (host, source). source ∈ explicit|cache|localhost|wsl-host."""
    if endpoint.host and endpoint.host != "127.0.0.1":
        return endpoint.host, "explicit"

    key = f"{endpoint.imap_port}:{endpoint.smtp_port}"
    if read_cache:
        cached = _read_cache(key)
        if cached and probe(cached, endpoint.imap_port) and probe(cached, endpoint.smtp_port):
            return cached, "cache"

    if probe("127.0.0.1", endpoint.imap_port) and probe("127.0.0.1", endpoint.smtp_port):
        if write_cache:
            _write_cache(key, "127.0.0.1")
        return "127.0.0.1", "localhost"

    if is_wsl():
        for host in candidates():
            if probe(host, endpoint.imap_port) and probe(host, endpoint.smtp_port):
                if write_cache:
                    _write_cache(key, host)
                return host, "wsl-host"

    raise ConnectionResolveError(
        "conn",
        "Proton Mail Bridge is unreachable",
        f"Neither 127.0.0.1 nor a Windows host answers on port "
        f"{endpoint.imap_port}/{endpoint.smtp_port}. "
        "Is the Bridge running? Check `proton-mail-bridge bridge doctor`.",
    )


def tls_context(endpoint: Endpoint) -> ssl.SSLContext:
    if endpoint.tls_cert_path:
        ctx = ssl.create_default_context(cafile=endpoint.tls_cert_path)
        return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx
