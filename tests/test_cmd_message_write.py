from __future__ import annotations

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox


def _patch(monkeypatch):
    mb = FakeMailBox()
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"))
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email))
    )
    return mb


def test_move_requires_yes_without_tty(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(main, ["message", "move", "--uid", "1", "--to", "Archive"])
    assert result.exit_code == 2  # geblockt (kein TTY, kein --yes)


def test_move_with_yes(monkeypatch):
    mb = _patch(monkeypatch)
    result = CliRunner().invoke(main, ["message", "move", "--uid", "1", "--to", "Archive", "--yes"])
    assert result.exit_code == 0
    assert mb.moved == [(["1"], "Archive")]


def test_mark_read_is_free(monkeypatch):
    mb = _patch(monkeypatch)
    result = CliRunner().invoke(main, ["message", "mark", "--uid", "1", "--read"])
    assert result.exit_code == 0
    assert mb.flagged == [(["1"], ["\\Seen"], True)]


def test_delete_expunge_blocked_without_tty(monkeypatch):
    _patch(monkeypatch)
    result = CliRunner().invoke(main, ["message", "delete", "--uid", "1", "--expunge"])
    assert result.exit_code == 2  # CRITICAL, kein TTY, kein Bypass


def test_delete_soft_moves_to_trash(monkeypatch):
    mb = _patch(monkeypatch)
    result = CliRunner().invoke(main, ["message", "delete", "--uid", "1", "--yes"])
    assert result.exit_code == 0
    assert mb.moved[0][1] == "Trash"
    assert mb.deleted == []


def test_copy_is_free(monkeypatch):
    mb = _patch(monkeypatch)
    result = CliRunner().invoke(main, ["message", "copy", "--uid", "1", "--to", "Archive"])
    assert result.exit_code == 0
    assert mb.copied == [(["1"], "Archive")]
