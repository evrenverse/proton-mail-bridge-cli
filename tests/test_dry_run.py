"""Dry-run semantics: a preview must be complete, and it must change nothing."""
from __future__ import annotations

import json

import click
from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint, save_config
from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox, FakeMessage

# Every command that changes state carries the flag -- and only those. Read-only commands
# have nothing to simulate; `account identity discover` is its own preview (without --save).
WRITING_COMMANDS = {
    "account add",
    "account add-raw",
    "account remove",
    "account set-default",
    "account identity add",
    "account identity remove",
    "account identity set-default",
    "bridge config",
    "mailbox create",
    "message move",
    "message copy",
    "message flag",
    "message mark",
    "message delete",
    "compose send",
    "compose reply",
    "compose forward",
    "compose draft",
    "attachment download",
    "skill install",
}


def _mailbox(monkeypatch, store=None, folder_flags=None) -> FakeMailBox:
    mb = FakeMailBox(store, folder_flags)
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"))
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email))
    )
    return mb


def _plan(result) -> dict:
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["dry_run"] is True
    return data


def _seed_config(tmp_path, monkeypatch, config) -> tuple:
    path = tmp_path / "config.toml"
    save_config(config, path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    return path, path.read_bytes()


def test_every_writing_command_offers_dry_run():
    """Pins the inventory: uniform semantics means no writing command may be missing."""
    found: set[str] = set()

    def walk(node: click.Command, path: list[str]) -> None:
        for name, cmd in getattr(node, "commands", {}).items():
            if isinstance(cmd, click.Group):
                walk(cmd, path + [name])
            elif any(p.name == "dry_run" for p in cmd.params):
                found.add(" ".join(path + [name]))

    walk(main, [])
    assert found == WRITING_COMMANDS


def test_move_dry_run_moves_nothing_and_names_every_message(monkeypatch):
    mb = _mailbox(monkeypatch, {"INBOX": [FakeMessage(uid="1"),
                                          FakeMessage(uid="2", subject="Second")]})
    data = _plan(CliRunner().invoke(main, ["--json", "message", "move", "--uid", "1,2",
                                           "--to", "Archive", "--dry-run"]))
    assert mb.moved == []
    assert data["action"] == "message move"
    assert data["account"] == "a@p.me"
    assert data["folder"] == "INBOX"
    assert data["to"] == "Archive"
    assert data["count"] == 2
    assert [m["uid"] for m in data["messages"]] == ["1", "2"]
    # the per-message fields are what makes the selection checkable
    assert {"uid", "folder", "date", "from", "subject", "size", "flags"} <= set(data["messages"][0])
    assert data["messages"][0]["from"] == "supplier@company.com"
    assert data["messages"][1]["subject"] == "Second"


def test_dry_run_never_marks_seen(monkeypatch):
    """A preview that sets \\Seen would itself be the accident it is meant to prevent."""
    mb = _mailbox(monkeypatch)
    _plan(CliRunner().invoke(main, ["--json", "message", "move", "--uid", "1",
                                    "--to", "Archive", "--dry-run"]))
    assert mb.flagged == []
    assert mb.fetch_calls
    assert all(c["mark_seen"] is False and c["headers_only"] for c in mb.fetch_calls)


def test_dry_run_reports_uids_the_folder_does_not_hold(monkeypatch):
    _mailbox(monkeypatch, {"INBOX": [FakeMessage(uid="1")]})
    data = _plan(CliRunner().invoke(main, ["--json", "message", "move", "--uid", "1,99",
                                           "--to", "Archive", "--dry-run"]))
    assert data["count"] == 1
    assert data["missing_uids"] == ["99"]


def test_bulk_dry_run_needs_no_confirmation(monkeypatch):
    """20 UIDs escalate the move to 🔴 -- the preview must stay reachable without a terminal."""
    uids = [str(i) for i in range(1, 21)]
    mb = _mailbox(monkeypatch, {"INBOX": [FakeMessage(uid=u) for u in uids]})
    data = _plan(CliRunner().invoke(main, ["--json", "message", "move", "--uid", ",".join(uids),
                                           "--to", "Archive", "--dry-run"]))
    assert data["risk"] == "critical"
    assert data["count"] == 20
    assert mb.moved == []


def test_delete_dry_run_names_the_trash_target(monkeypatch):
    mb = _mailbox(monkeypatch, {"INBOX": [FakeMessage()], "Papierkorb": []},
                  folder_flags={"Papierkorb": ("\\Trash",)})
    data = _plan(CliRunner().invoke(main, ["--json", "message", "delete", "--uid", "1",
                                           "--dry-run"]))
    assert data["permanent"] is False
    assert data["to"] == "Papierkorb"          # localized special-use name, resolved
    assert data["risk"] == "confirm"
    assert mb.moved == []
    assert mb.deleted == []


def test_delete_expunge_dry_run_runs_without_a_terminal(monkeypatch):
    """--expunge is 🔴 and terminal-only; its preview must not be, or it is useless to agents."""
    mb = _mailbox(monkeypatch)
    data = _plan(CliRunner().invoke(main, ["--json", "message", "delete", "--uid", "1",
                                           "--expunge", "--dry-run"]))
    assert data["permanent"] is True
    assert data["risk"] == "critical"
    assert data["to"] is None
    assert mb.deleted == []


def test_flag_mark_copy_dry_runs_change_nothing(monkeypatch):
    mb = _mailbox(monkeypatch)
    runner = CliRunner()
    flag = _plan(runner.invoke(main, ["--json", "message", "flag", "--uid", "1",
                                      "--remove", "\\Seen", "--dry-run"]))
    assert flag["remove"] == ["\\Seen"]
    assert flag["add"] == []
    assert flag["risk"] == "confirm"           # removing a flag is 🟡
    mark = _plan(runner.invoke(main, ["--json", "message", "mark", "--uid", "1",
                                      "--unread", "--dry-run"]))
    assert mark["remove"] == ["\\Seen"]
    copy = _plan(runner.invoke(main, ["--json", "message", "copy", "--uid", "1",
                                      "--to", "Archive", "--dry-run"]))
    assert copy["to"] == "Archive"
    assert mb.flagged == []
    assert mb.copied == []


def test_mailbox_create_dry_run_creates_nothing(monkeypatch):
    mb = _mailbox(monkeypatch)
    data = _plan(CliRunner().invoke(main, ["--json", "mailbox", "create", "Folders/New",
                                           "--dry-run"]))
    assert data["folder"] == "Folders/New"
    assert data["exists"] is False
    assert [f.name for f in mb.folder.list()] == ["INBOX"]


def test_draft_dry_run_appends_nothing(monkeypatch):
    mb = _mailbox(monkeypatch)
    data = _plan(CliRunner().invoke(main, ["--json", "compose", "draft", "--to", "a@x.de",
                                           "--subject", "S", "--body", "B", "--dry-run"]))
    assert mb.appended == []
    assert data["folder"] == "Drafts"
    assert data["from"] == "a@p.me"
    assert data["to"] == ["a@x.de"]


def test_attachment_download_dry_run_writes_nothing(monkeypatch, tmp_path):
    _mailbox(monkeypatch)
    target = tmp_path / "out"
    data = _plan(CliRunner().invoke(main, ["--json", "attachment", "download", "--uid", "1",
                                           "--all", "--dir", str(target), "--dry-run"]))
    assert not target.exists()                 # not even an empty directory is left behind
    assert data["count"] == 1
    assert data["files"][0]["filename"] == "invoice.pdf"
    assert data["files"][0]["target"] == str(target / "1_invoice.pdf")
    assert data["overwrites"] == []


def test_attachment_download_dry_run_flags_overwrites(monkeypatch, tmp_path):
    """The download overwrites silently -- naming the collisions is the point of the preview."""
    _mailbox(monkeypatch)
    existing = tmp_path / "1_invoice.pdf"
    existing.write_bytes(b"old")
    data = _plan(CliRunner().invoke(main, ["--json", "attachment", "download", "--uid", "1",
                                           "--all", "--dir", str(tmp_path), "--dry-run"]))
    assert data["overwrites"] == [str(existing)]
    assert existing.read_bytes() == b"old"


def test_account_remove_dry_run_leaves_the_config_untouched(tmp_path, monkeypatch):
    """No --yes and no terminal: the guard would block the real run, the preview must not be."""
    path, before = _seed_config(tmp_path, monkeypatch, Config(
        Endpoint(),
        [Account("a@p.me", "pw", alias="work"), Account("b@p.me", "pw")],
        "a@p.me",
    ))
    data = _plan(CliRunner().invoke(main, ["--json", "account", "remove", "work", "--dry-run"]))
    assert data["account"] == "a@p.me"
    assert data["risk"] == "confirm"
    assert data["new_default_account"] == "b@p.me"
    assert path.read_bytes() == before


def test_identity_dry_runs_leave_the_config_untouched(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import Identity

    path, before = _seed_config(tmp_path, monkeypatch, Config(
        Endpoint(),
        [Account("a@p.me", "pw", identities=[Identity("k@p.me", label="kontakt")],
                 default_identity="kontakt")],
        "a@p.me",
    ))
    runner = CliRunner()
    add = _plan(runner.invoke(main, ["--json", "account", "identity", "add",
                                     "--email", "neu@p.me", "--dry-run"]))
    assert add["identity"] == "neu@p.me"
    remove = _plan(runner.invoke(main, ["--json", "account", "identity", "remove", "kontakt",
                                        "--dry-run"]))
    assert remove["identity"] == "k@p.me"
    assert remove["clears_default_identity"] is True
    default = _plan(runner.invoke(main, ["--json", "account", "identity", "set-default",
                                         "k@p.me", "--dry-run"]))
    assert default["previous"] == "kontakt"
    assert path.read_bytes() == before


def test_bridge_config_dry_run_does_not_save(tmp_path, monkeypatch):
    path, before = _seed_config(tmp_path, monkeypatch, Config(
        Endpoint(), [Account("a@p.me", "pw")], "a@p.me"
    ))
    data = _plan(CliRunner().invoke(main, ["--json", "bridge", "config", "--host", "10.0.0.5",
                                           "--dry-run"]))
    assert data["host"] == "10.0.0.5"
    assert path.read_bytes() == before


def test_skill_install_dry_run_writes_nothing(tmp_path):
    dest = tmp_path / "skills"
    data = _plan(CliRunner().invoke(main, ["--json", "skill", "install", "--dest", str(dest),
                                           "--dry-run"]))
    assert not dest.exists()
    assert data["overwrites"] == []
    assert any(f.endswith("SKILL.md") for f in data["files"])
