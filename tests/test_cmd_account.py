from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core.config import Account, Config, Endpoint, save_config


def _seed(tmp_path):
    cfg = Config(
        endpoint=Endpoint(),
        accounts=[Account("a@p.me", "pw", alias="work")],
        default_account="a@p.me",
    )
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    return path


def test_account_list_json(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(main, ["--json", "account", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["accounts"][0]["email"] == "a@p.me"
    assert data["accounts"][0]["default"] is True


def test_account_set_default(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "add-raw", "--email", "b@p.me", "--password", "x"])
    result = CliRunner().invoke(main, ["account", "set-default", "b@p.me"])
    assert result.exit_code == 0
    from proton_mail_bridge.core.config import load_config
    assert load_config(path).default_account == "b@p.me"


def test_remove_by_alias_clears_stale_default(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    cfg = Config(endpoint=Endpoint(), accounts=[Account("a@p.me", "pw", alias="work")],
                 default_account="a@p.me")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(main, ["account", "remove", "work", "--yes"])
    assert result.exit_code == 0
    loaded = load_config(path)
    assert loaded.accounts == []
    assert loaded.default_account is None
