"""`--log`: what a delete removed, in a file that outlives the message."""
from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox, FakeMessage

NEWSLETTER = "<https://example.com/unsub>"


def _msg(uid: str, *, sender: str = "sender@example.com", bulk: bool = False,
         subject: str = "Subject", mid: str | None = None) -> FakeMessage:
    headers: dict = {"message-id": (f"<{mid or uid}@example.com>",)}
    if bulk:
        headers["list-unsubscribe"] = (NEWSLETTER,)
    return FakeMessage(uid=uid, from_=sender, subject=subject, headers=headers, attachments=[])


def _cli(monkeypatch, store: dict, folder_flags: dict | None = None) -> FakeMailBox:
    mb = FakeMailBox(store, folder_flags)
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"))
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email))
    )
    return mb


def _json(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _store() -> dict:
    """A labelled mail lives in its folder AND in All Mail -- own UID, same Message-ID."""
    return {
        "INBOX": [_msg("1", bulk=True, mid="a"), _msg("2", mid="b")],
        "Folders/Projects": [_msg("7", bulk=True, mid="c"), _msg("8", bulk=True, mid="d")],
        "All Mail": [_msg("30", bulk=True, mid="a"), _msg("31", bulk=True, mid="c"),
                     _msg("32", mid="b")],
        "Trash": [],
    }


FLAGS = {"All Mail": ("\\All",), "Trash": ("\\Trash",)}


def test_delete_log_records_what_disappeared(monkeypatch, tmp_path):
    """Without this, the only evidence for a permanently deleted message is its absence."""
    mb = _cli(monkeypatch, {"INBOX": [_msg("1", sender="who@example.com", subject="Gone")],
                            "Trash": []}, FLAGS)
    log = tmp_path / "deleted.jsonl"
    result = CliRunner().invoke(main, ["--json", "message", "delete", "--uid", "1",
                                       "--yes", "--log", str(log)])
    assert result.exit_code == 0
    assert mb.moved == [(["1"], "Trash")]
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["uid"] == "1"
    assert entry["folder"] == "INBOX"
    assert entry["from"] == "who@example.com"
    assert entry["subject"] == "Gone"
    assert entry["action"] == "message delete"
    assert entry["account"] == "a@p.me"
    assert entry["date"] and entry["ts"]


def test_delete_dry_run_names_the_log_but_writes_none(monkeypatch, tmp_path):
    _cli(monkeypatch, {"INBOX": [_msg("1")], "Trash": []}, FLAGS)
    log = tmp_path / "deleted.jsonl"
    data = _json(CliRunner().invoke(main, ["--json", "message", "delete", "--uid", "1",
                                           "--log", str(log), "--dry-run"]))
    assert data["log"] == str(log)
    assert not log.exists()


def test_bulk_delete_log_covers_every_folder(monkeypatch, tmp_path):
    _cli(monkeypatch, _store(), FLAGS)
    log = tmp_path / "purge.jsonl"
    result = CliRunner().invoke(main, ["--json", "message", "bulk-delete", "--all-folders",
                                       "--list-unsubscribe", "--yes", "--log", str(log)])
    assert result.exit_code == 0
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(lines) == 3
    assert {x["folder"] for x in lines} == {"INBOX", "Folders/Projects"}
