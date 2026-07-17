from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import connection


def test_doctor_reports_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setattr(connection, "detect_wsl", lambda: True)
    monkeypatch.setattr(connection, "windows_host_candidates", lambda: ["172.20.0.1"])
    monkeypatch.setattr(connection, "probe", lambda h, p, timeout=1.0: h == "127.0.0.1")
    monkeypatch.setattr(connection, "detect_security",
                        lambda h, p, **k: "ssl" if p == 1025 else "starttls")
    result = CliRunner().invoke(main, ["--json", "bridge", "doctor"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["wsl"] is True
    assert data["reachable"] is True
    assert data["resolved_host"] == "127.0.0.1"
    assert data["imap_security"] == "starttls"
    assert data["smtp_security"] == "ssl"
    assert "--smtp-security ssl" in data["hint"]  # detected mismatch → fix hint
