from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.smtp import SmtpSession


def _patch(monkeypatch, sent, config=None):
    from proton_mail_bridge.core.config import Identity

    default = Config(
        Endpoint(),
        [Account("me@p.me", "pw",
                 identities=[Identity("kontakt@p.me", name="Kontakt", label="kontakt")])],
        "me@p.me",
    )
    monkeypatch.setattr(cfgmod, "resolve_config", lambda *a, **k: config or default)

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def send(self, msg):
            sent.append(msg)
            return msg["Message-ID"]

    monkeypatch.setattr(
        SmtpSession, "connect", classmethod(lambda cls, ep, acc, **k: FakeSession())
    )
    return default


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


def test_send_with_identity_sets_display_name(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    result = CliRunner().invoke(main, ["--json", "compose", "send", "--to", "a@x.de",
                                       "--subject", "S", "--body", "B",
                                       "--identity", "kontakt", "--yes"])
    assert result.exit_code == 0
    assert sent[0]["From"] == "Kontakt <kontakt@p.me>"
    data = json.loads(result.output)
    assert data["from"] == "kontakt@p.me"
    assert data["account"] == "me@p.me"


def test_send_without_identity_uses_login_address(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    result = CliRunner().invoke(main, ["--json", "compose", "send", "--to", "a@x.de",
                                       "--subject", "S", "--body", "B", "--yes"])
    assert result.exit_code == 0
    assert sent[0]["From"] == "me@p.me"


def test_send_unknown_identity_never_connects(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    connects = []
    monkeypatch.setattr(
        SmtpSession, "connect",
        classmethod(lambda cls, ep, acc, **k: connects.append(acc.email)),
    )
    result = CliRunner().invoke(main, ["--json", "compose", "send", "--to", "a@x.de",
                                       "--subject", "S", "--body", "B",
                                       "--identity", "tippfehler", "--yes"])
    assert result.exit_code != 0
    assert connects == []            # strict check happens before the connection is opened
    assert sent == []
    assert json.loads(result.output)["error"]["title"] == "Unknown identity"


def test_dry_run_reports_the_identity(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    result = CliRunner().invoke(main, ["--json", "compose", "send", "--to", "a@x.de",
                                       "--subject", "S", "--body", "B",
                                       "--identity", "kontakt", "--dry-run"])
    assert json.loads(result.output)["from"] == "kontakt@p.me"


def test_draft_uses_identity(monkeypatch):
    from proton_mail_bridge.core.config import Identity
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox
    mb = FakeMailBox()
    monkeypatch.setattr(
        cfgmod, "resolve_config",
        lambda *a, **k: Config(
            Endpoint(),
            [Account("me@p.me", "pw",
                     identities=[Identity("kontakt@p.me", name="Kontakt", label="kontakt")])],
            "me@p.me",
        ),
    )
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email))
    )
    result = CliRunner().invoke(
        main, ["compose", "draft", "--to", "a@x.de", "--subject", "S", "--body", "B",
               "--identity", "kontakt"]
    )
    assert result.exit_code == 0
    assert len(mb.appended) == 1
    assert b"From: Kontakt <kontakt@p.me>" in mb.appended[0][2]


def test_reply_uses_the_addressed_identity(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    msg = FakeMessage(to=("kontakt@p.me",))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(main, ["compose", "reply", "--uid", "1", "--body", "ok", "--yes"])
    assert result.exit_code == 0
    assert sent[0]["From"] == "Kontakt <kontakt@p.me>"


def test_reply_all_drops_every_own_address(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    msg = FakeMessage(to=("kontakt@p.me", "other@x.de"), cc=("me@p.me", "cc@x.de"))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["compose", "reply", "--uid", "1", "--all", "--body", "ok", "--yes"]
    )
    assert result.exit_code == 0
    assert sent[0]["To"] == "supplier@company.com, other@x.de"  # kontakt@p.me removed
    assert sent[0]["Cc"] == "cc@x.de"                            # me@p.me removed


def test_reply_identity_flag_overrides_automatic_choice(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    msg = FakeMessage(to=("me@p.me",))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["compose", "reply", "--uid", "1", "--body", "ok", "--identity", "kontakt", "--yes"]
    )
    assert result.exit_code == 0
    assert sent[0]["From"] == "Kontakt <kontakt@p.me>"


def test_reply_dry_run_reveals_the_automatic_sender(monkeypatch):
    """The dry run is the only place a human can check the automatic sender choice."""
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    msg = FakeMessage(to=("kontakt@p.me",))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["--json", "compose", "reply", "--uid", "1", "--body", "ok", "--dry-run"]
    )
    assert result.exit_code == 0
    assert sent == []
    data = json.loads(result.output)
    assert data["from"] == "kontakt@p.me"
    assert data["account"] == "me@p.me"


def test_forward_uses_the_addressed_identity(monkeypatch):
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    msg = FakeMessage(to=("kontakt@p.me",))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["compose", "forward", "--uid", "1", "--to", "x@y.de", "--yes"]
    )
    assert result.exit_code == 0
    assert sent[0]["From"] == "Kontakt <kontakt@p.me>"


def test_forward_reads_the_identity_from_delivered_to(monkeypatch):
    """Pins include_headers=True: without the headers the Delivered-To address is invisible."""
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    msg = FakeMessage(
        to=("wer@x.de",),
        headers={"message-id": ("<m1@company.com>",),
                 "delivered-to": ("Kontakt <kontakt@p.me>",)},
    )
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["compose", "forward", "--uid", "1", "--to", "x@y.de", "--yes"]
    )
    assert result.exit_code == 0
    assert sent[0]["From"] == "Kontakt <kontakt@p.me>"


def test_reply_to_a_missing_uid_names_the_mailbox(monkeypatch):
    """An --identity may retarget the account, so the error must say where we looked."""
    sent = []
    _patch(monkeypatch, sent)
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": []}), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["--json", "compose", "reply", "--uid", "99", "--body", "ok", "--yes"]
    )
    assert result.exit_code != 0
    assert sent == []
    error = json.loads(result.output)["error"]
    assert error["title"] == "Message not found"
    assert error["detail"] == "uid=99 in INBOX of me@p.me"
