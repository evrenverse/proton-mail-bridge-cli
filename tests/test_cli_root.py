from __future__ import annotations

from click.testing import CliRunner

from proton_mail_bridge.cli import main


def test_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    from proton_mail_bridge import __version__
    assert __version__ in result.output


def test_help_lists_groups():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for group in ("account", "bridge", "mailbox", "message", "compose", "attachment"):
        assert group in result.output


def test_unexpected_exception_keeps_json_contract(monkeypatch):
    """No raw traceback for agents — every error arrives as JSON (macOS smoke finding)."""
    import json

    from proton_mail_bridge.core import config as cfgmod

    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(cfgmod, "resolve_config", boom)
    result = CliRunner().invoke(main, ["--json", "message", "list"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["type"] == "error"
    assert data["error"]["title"] == "TimeoutError"


def test_usage_error_emits_json():
    import json
    result = CliRunner().invoke(main, ["--json", "message", "search", "--no-such-flag"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["type"] == "usage"


def test_bridge_error_emits_json(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(tmp_path / "none.toml"))
    result = CliRunner().invoke(main, ["--json", "message", "list"])
    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["type"] == "auth"
