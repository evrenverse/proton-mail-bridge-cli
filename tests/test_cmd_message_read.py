from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox


def _patch(monkeypatch, accounts):
    monkeypatch.setattr(
        cfgmod, "resolve_config",
        lambda *a, **k: Config(Endpoint(), accounts, accounts[0].email),
    )
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox(), acc.email)),
    )


def test_search_fans_out_over_all_accounts(monkeypatch):
    _patch(monkeypatch, [Account("a@p.me", "1"), Account("b@p.me", "2")])
    result = CliRunner().invoke(main, ["--json", "message", "search", "--subject", "Container"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {r["account"] for r in data} == {"a@p.me", "b@p.me"}
    assert data[0]["items"][0]["subject"] == "Container order"


def test_search_count_only_uses_uid_search(monkeypatch):
    _patch(monkeypatch, [Account("a@p.me", "1")])
    result = CliRunner().invoke(main, ["--json", "message", "search", "--count-only"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["items"] == {"folder": "INBOX", "count": 1}


def test_search_count_only_rejects_client_filters(monkeypatch):
    _patch(monkeypatch, [Account("a@p.me", "1")])
    result = CliRunner().invoke(
        main, ["--json", "message", "search", "--count-only", "--text", "x"]
    )
    assert result.exit_code != 0
    assert json.loads(result.output)["error"]["type"] == "usage"


def test_search_ids_only_strips_records(monkeypatch):
    _patch(monkeypatch, [Account("a@p.me", "1")])
    result = CliRunner().invoke(main, ["--json", "message", "search", "--ids-only"])
    assert result.exit_code == 0
    rec = json.loads(result.output)[0]["items"][0]
    assert set(rec) == {"account", "folder", "uid", "message_id"}


def test_search_has_attachments_filters(monkeypatch):
    from tests.conftest import FakeMessage
    with_att = FakeMessage(uid="1")
    without = FakeMessage(uid="2", attachments=[],
                          headers={"message-id": ("<m2@company.com>",)})
    mb = FakeMailBox({"INBOX": [with_att, without]})
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "1")], "a@p.me"))
    monkeypatch.setattr(ImapClient, "connect",
                        classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email)))
    result = CliRunner().invoke(main, ["--json", "message", "search", "--has-attachments"])
    assert result.exit_code == 0
    items = json.loads(result.output)[0]["items"]
    assert [r["uid"] for r in items] == ["1"]


def test_read_single_account(monkeypatch):
    _patch(monkeypatch, [Account("a@p.me", "1")])
    result = CliRunner().invoke(
        main, ["--json", "message", "read", "--uid", "1", "--format", "text"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["items"][0]["body_text"] == "We order 3 containers."


def test_read_mark_read_sets_seen(monkeypatch):
    mb = FakeMailBox()
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "1")], "a@p.me"))
    monkeypatch.setattr(ImapClient, "connect",
                        classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email)))
    result = CliRunner().invoke(main, ["--json", "message", "read", "--uid", "1", "--mark-read"])
    assert result.exit_code == 0
    assert mb.flagged == [(["1"], ["\\Seen"], True)]
