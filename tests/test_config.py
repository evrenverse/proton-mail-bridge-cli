from __future__ import annotations

import pytest

from proton_mail_bridge.core import config as cfg
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.errors import AccountSelectionError


def _config(accounts, default=None):
    return Config(endpoint=Endpoint(), accounts=accounts, default_account=default)


def test_env_overrides_build_single_account():
    env = {
        "PROTON_BRIDGE_HOST": "10.0.0.5",
        "PROTON_BRIDGE_SMTP_PORT": "2025",
        "PROTON_BRIDGE_USER": "me@proton.me",
        "PROTON_BRIDGE_PASS": "secret",
    }
    c = cfg.resolve_config(path=None, env=env, load_file=False)
    assert c.endpoint.host == "10.0.0.5"
    assert c.endpoint.smtp_port == 2025
    assert [a.email for a in c.accounts] == ["me@proton.me"]


def test_legacy_port_alias_maps_to_smtp():
    env = {"PROTON_BRIDGE_PORT": "1099", "PROTON_BRIDGE_USER": "x@p.me", "PROTON_BRIDGE_PASS": "y"}
    c = cfg.resolve_config(path=None, env=env, load_file=False)
    assert c.endpoint.smtp_port == 1099


def test_find_account_by_email_or_alias():
    c = _config([Account("a@p.me", "pw", alias="work")])
    assert cfg.find_account(c, "a@p.me").email == "a@p.me"
    assert cfg.find_account(c, "work").email == "a@p.me"
    assert cfg.find_account(c, "nope") is None


def test_read_mode_defaults_to_all_accounts():
    c = _config([Account("a@p.me", "1"), Account("b@p.me", "2")], default="a@p.me")
    got = cfg.resolve_accounts(c, None, mode="read")
    assert {a.email for a in got} == {"a@p.me", "b@p.me"}  # default_account does NOT restrict


def test_identity_mode_uses_default_then_fails():
    multi = _config([Account("a@p.me", "1"), Account("b@p.me", "2")], default="b@p.me")
    assert [a.email for a in cfg.resolve_accounts(multi, None, mode="identity")] == ["b@p.me"]
    no_default = _config([Account("a@p.me", "1"), Account("b@p.me", "2")])
    with pytest.raises(AccountSelectionError):
        cfg.resolve_accounts(no_default, None, mode="identity")


def test_message_op_mode_requires_explicit_when_multiple():
    multi = _config([Account("a@p.me", "1"), Account("b@p.me", "2")], default="a@p.me")
    with pytest.raises(AccountSelectionError):  # default_account does NOT count here
        cfg.resolve_accounts(multi, None, mode="message_op")
    assert [a.email for a in cfg.resolve_accounts(multi, "b@p.me", mode="message_op")] == ["b@p.me"]


def test_explicit_all_returns_all():
    c = _config([Account("a@p.me", "1"), Account("b@p.me", "2")])
    assert len(cfg.resolve_accounts(c, "all", mode="identity")) == 2


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    c = Config(
        endpoint=Endpoint(host="1.2.3.4", smtp_port=2025, security="ssl", timeout=12.5),
        accounts=[Account("a@p.me", "pw1", alias=None), Account("b@p.me", "pw2", alias="work")],
        default_account="a@p.me",
    )
    cfg.save_config(c, path)
    loaded = cfg.load_config(path)
    assert loaded.endpoint.host == "1.2.3.4"
    assert loaded.endpoint.smtp_port == 2025
    assert loaded.endpoint.security == "ssl"
    assert loaded.endpoint.timeout == 12.5
    assert loaded.endpoint.smtp_security is None  # None = inherits security
    assert loaded.default_account == "a@p.me"
    assert [(a.email, a.password, a.alias) for a in loaded.accounts] == [
        ("a@p.me", "pw1", None), ("b@p.me", "pw2", "work")]


def test_smtp_security_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    c = Config(endpoint=Endpoint(smtp_security="ssl"), accounts=[Account("a@p.me", "pw")])
    cfg.save_config(c, path)
    assert cfg.load_config(path).endpoint.smtp_security == "ssl"
