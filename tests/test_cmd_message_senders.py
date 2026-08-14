"""`message senders`: who sends the most, counted over the whole scope."""
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


FLAGS = {"All Mail": ("\\All",), "Trash": ("\\Trash",)}


def _json(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_senders_ranks_by_count_with_last_mail_and_unsubscribe_hint(monkeypatch):
    _cli(monkeypatch, {"INBOX": [
        _msg("1", sender="rare@example.com", subject="Once"),
        _msg("2", sender="news@example.org", bulk=True, subject="Older"),
        _msg("3", sender="news@example.org", bulk=True, subject="Newest"),
    ]}, FLAGS)
    data = _json(CliRunner().invoke(main, [
        "--json", "message", "senders", "--folder", "INBOX",
    ]))[0]
    top = data["items"][0]
    assert top["from"] == "news@example.org"
    assert top["count"] == 2
    assert top["last_subject"] == "Newest"          # newest first → first hit wins
    assert top["list_unsubscribe"] is True
    assert data["senders"]["scanned"] == 3
    assert data["items"][1]["list_unsubscribe"] is False


def test_senders_min_count_filters(monkeypatch):
    _cli(monkeypatch, {"INBOX": [_msg("1", sender="a@example.com"),
                                 _msg("2", sender="b@example.com"),
                                 _msg("3", sender="b@example.com")]}, FLAGS)
    data = _json(CliRunner().invoke(main, [
        "--json", "message", "senders", "--folder", "INBOX", "--min-count", "2",
    ]))[0]
    assert [r["from"] for r in data["items"]] == ["b@example.com"]
    assert data["senders"]["senders_total"] == 1


def test_senders_reads_headers_only(monkeypatch):
    mb = _cli(monkeypatch, {"INBOX": [_msg("1")]}, FLAGS)
    CliRunner().invoke(main, ["--json", "message", "senders", "--folder", "INBOX"])
    assert mb.fetch_calls
    assert all(c["headers_only"] and c["mark_seen"] is False for c in mb.fetch_calls)


def test_senders_across_folders_counts_a_mail_once_but_names_every_copy(monkeypatch):
    """A labelled mail is one message in two folders: the count must not double, and the
    cleanup still has to know that both folders hold a copy."""
    _cli(monkeypatch, {
        "INBOX": [_msg("1", sender="news@example.org", mid="a")],
        "Labels/News": [_msg("40", sender="news@example.org", mid="a")],
        "All Mail": [_msg("90", sender="news@example.org", mid="a")],
    }, FLAGS)
    data = _json(CliRunner().invoke(main, ["--json", "message", "senders", "--all-folders"]))[0]
    row = data["items"][0]
    assert row["count"] == 1                                  # deduplicated by Message-ID
    assert row["folders"] == {"INBOX": 1, "Labels/News": 1}    # both copies named
    assert data["senders"]["skipped_folders"] == ["All Mail"]  # duplicate view, no news
    assert data["senders"]["folders"] == ["INBOX", "Labels/News"]


def test_senders_last_mail_wins_across_folders_regardless_of_utc_offset(monkeypatch):
    """Within a folder the scan is newest first; across folders it is not, and ISO strings
    with different offsets do not sort as text."""
    from datetime import UTC, datetime, timedelta, timezone

    older = _msg("1", sender="a@example.org", subject="Older", mid="x")
    older.date = datetime(2026, 8, 14, 10, 0, tzinfo=timezone(timedelta(hours=2)))  # 08:00Z
    newer = _msg("2", sender="a@example.org", subject="Newer", mid="y")
    newer.date = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)                            # 09:00Z
    _cli(monkeypatch, {"INBOX": [older], "Archive": [newer]}, FLAGS)
    data = _json(CliRunner().invoke(main, ["--json", "message", "senders", "--all-folders"]))[0]
    row = data["items"][0]
    assert row["count"] == 2
    assert row["last_subject"] == "Newer"      # lexicographically it would have been "Older"


def test_senders_single_folder_scope_keeps_all_mail(monkeypatch):
    """All Mail is skipped only when it duplicates other folders in the same scan."""
    _cli(monkeypatch, {"INBOX": [_msg("1")], "All Mail": [_msg("9", mid="z")]}, FLAGS)
    data = _json(CliRunner().invoke(main, ["--json", "message", "senders"]))[0]
    assert data["senders"]["folders"] == ["All Mail"]
    assert data["senders"]["skipped_folders"] == []
    assert data["items"][0]["count"] == 1
