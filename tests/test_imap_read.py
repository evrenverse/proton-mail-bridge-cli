from __future__ import annotations

from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox


def test_search_returns_summaries():
    client = ImapClient(FakeMailBox(), account_email="me@p.me")
    res = client.search({}, folder="INBOX", limit=None, with_body=False, with_attachments=False)
    assert len(res) == 1
    s = res[0]
    assert s["account"] == "me@p.me"
    assert s["uid"] == "1"
    assert s["subject"] == "Container order"
    assert s["has_attachments"] is True
    assert s["attachment_count"] == 1
    assert "body_text" not in s
    assert s["date"].startswith("2026-01-02T09:30")


def test_search_newest_first_with_limit():
    from datetime import UTC, datetime

    from tests.conftest import FakeMessage
    old = FakeMessage(uid="1", date=datetime(2026, 1, 1, tzinfo=UTC))
    new = FakeMessage(uid="2", date=datetime(2026, 1, 5, tzinfo=UTC))
    client = ImapClient(FakeMailBox({"INBOX": [old, new]}), account_email="me@p.me")
    res = client.search({}, folder="INBOX", limit=1, with_body=False, with_attachments=False)
    assert [r["uid"] for r in res] == ["2"]  # newest first, limit applies after reversing


def test_search_with_body_includes_text():
    client = ImapClient(FakeMailBox(), account_email="me@p.me")
    res = client.search({}, folder="INBOX", limit=None, with_body=True, with_attachments=False)
    assert res[0]["body_text"] == "We order 3 containers."


def test_list_folders():
    client = ImapClient(FakeMailBox(), account_email="me@p.me")
    assert "INBOX" in client.list_folders()


def test_criteria_non_empty():
    from imap_tools import AND
    client = ImapClient(FakeMailBox(), account_email="me@p.me")
    assert isinstance(client._criteria({"seen": True}), AND)


def test_folder_status():
    client = ImapClient(FakeMailBox(), account_email="me@p.me")
    st = client.folder_status("INBOX")
    assert st["MESSAGES"] == 1
