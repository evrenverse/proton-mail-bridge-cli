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


def test_identity_add_and_list(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    add = CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                                    "--name", "Kontakt", "--label", "kontakt"])
    assert add.exit_code == 0
    result = CliRunner().invoke(main, ["--json", "account", "list"])
    row = json.loads(result.output)["accounts"][0]
    assert {i["email"] for i in row["identities"]} == {"a@p.me", "k@p.me"}   # Login implizit
    assert row["default_identity"] is None


def test_identity_add_rejects_duplicates(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    dup_mail = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                         "--email", "k@p.me"])
    assert dup_mail.exit_code != 0
    mail_error = json.loads(dup_mail.output)["error"]
    assert mail_error["title"] == "Identity already exists"
    assert mail_error["detail"] == "k@p.me"
    dup_label = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                          "--email", "x@p.me", "--label", "kontakt"])
    assert dup_label.exit_code != 0
    label_error = json.loads(dup_label.output)["error"]
    assert label_error["title"] == "Label already used"
    assert label_error["detail"] == "kontakt"
    # neither rejected duplicate was appended — the account still holds just the first entry
    assert len(load_config(path).accounts[0].identities) == 1


def test_identity_add_rejects_duplicates_case_insensitively(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    dup_mail = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                         "--email", "K@p.me"])
    assert dup_mail.exit_code != 0
    dup_label = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                          "--email", "y@p.me", "--label", "Kontakt"])
    assert dup_label.exit_code != 0
    # a case-shifted duplicate must not shadow the original entry
    assert len(load_config(path).accounts[0].identities) == 1


def test_identity_set_default_and_remove(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    assert CliRunner().invoke(main, ["account", "identity", "set-default",
                                     "kontakt"]).exit_code == 0
    assert load_config(path).accounts[0].default_identity == "kontakt"
    remove = CliRunner().invoke(main, ["account", "identity", "remove", "kontakt", "--yes"])
    assert remove.exit_code == 0
    account = load_config(path).accounts[0]
    assert account.identities == []
    assert account.default_identity is None   # veralteter Default wird geleert


def test_identity_remove_refuses_the_login_address(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(
        main, ["--json", "account", "identity", "remove", "a@p.me", "--yes"]
    )
    assert result.exit_code != 0
    assert "login" in json.loads(result.output)["error"]["detail"].lower()


def test_identity_remove_rejects_blank_value(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    CliRunner().invoke(main, ["account", "identity", "set-default", "kontakt"])
    result = CliRunner().invoke(main, ["--json", "account", "identity", "remove", "", "--yes"])
    assert result.exit_code != 0
    # a blank VALUE must not fall back to (and delete) the current default identity
    account = load_config(path).accounts[0]
    assert len(account.identities) == 1
    assert account.default_identity == "kontakt"
