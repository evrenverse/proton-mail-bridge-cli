from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox


def _patch(monkeypatch):
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox(), acc.email)),
    )


def test_mailbox_create(monkeypatch):
    mb = FakeMailBox()
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email)),
    )
    result = CliRunner().invoke(main, ["--json", "mailbox", "create", "Folders/Invoices"])
    assert result.exit_code == 0
    assert "Folders/Invoices" in mb._store


def test_mailbox_list(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(main, ["--json", "mailbox", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["account"] == "a@p.me"
    assert any(f["name"] == "INBOX" for f in data[0]["items"]["folders"])
