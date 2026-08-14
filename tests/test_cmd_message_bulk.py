"""Bulk operations: select by criteria, run folder by folder."""
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


def test_bulk_move_runs_folder_by_folder_and_reports_each(monkeypatch):
    mb = _cli(monkeypatch, _store(), FLAGS)
    data = _json(CliRunner().invoke(main, [
        "--json", "message", "bulk-move", "--all-folders", "--list-unsubscribe",
        "--dest", "Folders/Archive", "--yes",
    ]))
    assert data["total"] == 3
    assert {(g["folder"], g["count"]) for g in data["folders"]} == {
        ("INBOX", 1), ("Folders/Projects", 2),
    }
    assert mb.moved == [(["1"], "Folders/Archive"), (["8", "7"], "Folders/Archive")]  # newest 1st


def test_bulk_ops_skip_all_mail_because_it_duplicates_every_other_folder(monkeypatch):
    """All Mail is read-only and holds the same mails again -- hits there are never news."""
    mb = _cli(monkeypatch, _store(), FLAGS)
    data = _json(CliRunner().invoke(main, [
        "--json", "message", "bulk-move", "--all-folders", "--list-unsubscribe",
        "--dest", "Folders/Archive", "--yes",
    ]))
    assert "All Mail" in data["search"]["skipped_folders"]
    assert all(g["folder"] != "All Mail" for g in data["folders"])
    assert all("30" not in uids for uids, _ in mb.moved)


def test_bulk_delete_dry_run_touches_nothing_and_names_every_message(monkeypatch):
    mb = _cli(monkeypatch, _store(), FLAGS)
    data = _json(CliRunner().invoke(main, [
        "--json", "message", "bulk-delete", "--all-folders", "--list-unsubscribe", "--dry-run",
    ]))
    assert data["dry_run"] is True
    assert data["action"] == "message bulk-delete"
    assert data["permanent"] is False
    assert data["to"] == "Trash"
    assert data["total"] == 3
    inbox = next(g for g in data["folders"] if g["folder"] == "INBOX")
    assert inbox["uids"] == ["1"]
    assert {"uid", "folder", "date", "from", "subject"} <= set(inbox["messages"][0])
    assert mb.moved == [] and mb.deleted == []


def test_bulk_delete_expunge_is_critical_and_blocked_without_a_terminal(monkeypatch):
    mb = _cli(monkeypatch, _store(), FLAGS)
    result = CliRunner().invoke(main, [
        "--json", "message", "bulk-delete", "--folder", "INBOX", "--list-unsubscribe",
        "--expunge", "--yes",
    ])
    assert result.exit_code == 2          # --yes is no bypass for 🔴
    assert mb.deleted == []
    plan = _json(CliRunner().invoke(main, [
        "--json", "message", "bulk-delete", "--folder", "INBOX", "--list-unsubscribe",
        "--expunge", "--dry-run",
    ]))
    assert plan["risk"] == "critical" and plan["permanent"] is True


def test_bulk_delete_soft_moves_to_trash_and_leaves_trash_alone(monkeypatch):
    mb = _cli(monkeypatch, _store(), FLAGS)
    data = _json(CliRunner().invoke(main, [
        "--json", "message", "bulk-delete", "--all-folders", "--list-unsubscribe", "--yes",
    ]))
    assert data["to"] == "Trash"
    assert "Trash" in data["search"]["skipped_folders"]
    assert [dest for _, dest in mb.moved] == ["Trash", "Trash"]


def test_bulk_selection_matches_the_search_selection(monkeypatch):
    """Same options, same hits -- otherwise the dry run would preview a different set."""
    _cli(monkeypatch, _store(), FLAGS)
    found = _json(CliRunner().invoke(main, [
        "--json", "message", "search", "--all-folders", "--list-unsubscribe", "--ids-only",
        "--limit", "0",
    ]))[0]
    plan = _json(CliRunner().invoke(main, [
        "--json", "message", "bulk-delete", "--all-folders", "--list-unsubscribe", "--dry-run",
    ]))
    # search dedups by Message-ID over All Mail, bulk skips the folder -- same messages
    assert {r["uid"] for r in found["items"]} == {
        u for g in plan["folders"] for u in g["uids"]
    }


def test_bulk_move_with_no_hits_changes_nothing(monkeypatch):
    mb = _cli(monkeypatch, _store(), FLAGS)
    data = _json(CliRunner().invoke(main, [
        "--json", "message", "bulk-move", "--folder", "INBOX", "--subject", "nothing-matches",
        "--text", "nothing-matches", "--dest", "Folders/Archive", "--yes",
    ]))
    assert data["total"] == 0 and data["folders"] == []
    assert mb.moved == []
