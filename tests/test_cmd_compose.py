from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.smtp import SmtpSession


def _patch(monkeypatch, sent):
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("me@p.me", "pw")], "me@p.me"))

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def send(self, msg):
            sent.append(msg)
            return msg["Message-ID"]

    monkeypatch.setattr(
        SmtpSession, "connect", classmethod(lambda cls, ep, acc, **k: FakeSession())
    )


def test_send_dry_run_does_not_send(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    result = CliRunner().invoke(main, ["--json", "compose", "send", "--to", "a@x.de",
                                       "--subject", "S", "--body", "B", "--dry-run"])
    assert result.exit_code == 0
    assert sent == []
    assert json.loads(result.output)["dry_run"] is True


def test_send_with_yes(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    result = CliRunner().invoke(main, ["--json", "compose", "send", "--to", "a@x.de",
                                       "--subject", "S", "--body", "B", "--yes"])
    assert result.exit_code == 0
    assert len(sent) == 1
    assert sent[0]["To"] == "a@x.de"


def test_forward_includes_attachments(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox(), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["compose", "forward", "--uid", "1", "--to", "x@y.de", "--yes"]
    )
    assert result.exit_code == 0
    names = [p.get_filename() for p in sent[0].iter_attachments()]
    assert "invoice.pdf" in names


def test_reply_all_excludes_self_and_keeps_cc(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    msg = FakeMessage(to=("me@p.me", "other@x.de"), cc=("cc@x.de",))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["compose", "reply", "--uid", "1", "--all", "--body", "ok", "--yes"]
    )
    assert result.exit_code == 0
    assert sent[0]["To"] == "supplier@company.com, other@x.de"   # own address removed
    assert sent[0]["Cc"] == "cc@x.de"


def test_draft_is_free_and_appends(monkeypatch):
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox
    mb = FakeMailBox()
    monkeypatch.setattr(
        cfgmod, "resolve_config",
        lambda *a, **k: Config(Endpoint(), [Account("me@p.me", "pw")], "me@p.me"),
    )
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email)),
    )
    result = CliRunner().invoke(
        main, ["compose", "draft", "--to", "a@x.de", "--subject", "S", "--body", "B"]
    )
    assert result.exit_code == 0  # FREE: no --yes needed
    assert len(mb.appended) == 1
