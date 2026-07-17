from __future__ import annotations

from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox


def test_fetch_by_uid_returns_full():
    mb = FakeMailBox()
    client = ImapClient(mb, account_email="me@p.me")
    res = client.fetch(["1"], folder="INBOX", fmt="text", include_headers=True)
    assert res[0]["body_text"] == "We order 3 containers."
    assert res[0]["headers"]["message-id"] == ["<m1@company.com>"]


def test_move_and_flag_and_delete():
    mb = FakeMailBox()
    client = ImapClient(mb, account_email="me@p.me")
    client.move(["1"], folder="INBOX", dest="Archive")
    client.set_flags(["1"], folder="INBOX", add=["\\Flagged"], remove=[])
    client.delete(["1"], folder="INBOX")
    assert mb.moved == [(["1"], "Archive")]
    assert mb.flagged == [(["1"], ["\\Flagged"], True)]
    assert mb.deleted == [["1"]]


def test_copy_records_separately():
    mb = FakeMailBox()
    client = ImapClient(mb, account_email="me@p.me")
    client.copy(["1"], folder="INBOX", dest="Archive")
    assert mb.copied == [(["1"], "Archive")]
    assert mb.moved == []


def test_special_folders_and_resolve():
    # localized names + special-use flags (e.g. a German bridge)
    store = {"INBOX": [], "Alle Nachrichten": [], "Gesendet": []}
    flags = {"Alle Nachrichten": ("\\All",), "Gesendet": ("\\Sent",)}
    client = ImapClient(FakeMailBox(store, folder_flags=flags), account_email="me@p.me")
    assert client.special_folders() == {"all": "Alle Nachrichten", "sent": "Gesendet"}
    assert client.resolve_folder(None, "all") == "Alle Nachrichten"   # default → All Mail
    assert client.resolve_folder("INBOX", "all") == "INBOX"           # explicit wins
    assert client.resolve_folder(None, "trash") == "INBOX"            # unknown → fallback
