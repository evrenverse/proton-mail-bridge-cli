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


def test_attachment_list(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(main, ["--json", "attachment", "list", "--uid", "1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["items"][0]["filename"] == "invoice.pdf"


def test_attachment_download(monkeypatch, tmp_path):
    _patch(monkeypatch)
    result = CliRunner().invoke(main, ["--json", "attachment", "download", "--uid", "1",
                                       "--all", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    # filename now carries a UID prefix (collision-safe): 1_invoice.pdf
    matches = list(tmp_path.glob("*invoice.pdf"))
    assert matches and matches[0].read_bytes().startswith(b"%PDF")


def test_download_sanitizes_malicious_filename(monkeypatch, tmp_path):
    from tests.conftest import FakeAttachment, FakeMailBox, FakeMessage
    evil = FakeMessage(attachments=[FakeAttachment("../../evil.pdf", payload=b"%PDF-x")])
    monkeypatch.setattr(
        cfgmod, "resolve_config",
        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"),
    )
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(
            lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [evil]}), acc.email)
        ),
    )
    result = CliRunner().invoke(
        main, ["attachment", "download", "--uid", "1", "--all", "--dir", str(tmp_path)]
    )
    assert result.exit_code == 0
    # filename now carries a UID prefix: 1_evil.pdf (no path traversal)
    matches = list(tmp_path.glob("*evil.pdf"))
    assert matches and matches[0].read_bytes().startswith(b"%PDF")    # Basename, im dir
    assert not (tmp_path.parent / "evil.pdf").exists()                # no escape


def test_extract_to_stdout(monkeypatch):
    from tests.conftest import FakeMailBox
    monkeypatch.setattr(
        cfgmod, "resolve_config",
        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"),
    )
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox(), acc.email)),
    )
    result = CliRunner().invoke(
        main, ["attachment", "extract", "--uid", "1", "--name", "invoice.pdf"]
    )
    assert result.exit_code == 0
