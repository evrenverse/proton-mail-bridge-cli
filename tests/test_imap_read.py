from __future__ import annotations

from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox


def test_search_returns_summaries():
    client = ImapClient(FakeMailBox(), account_email="me@p.me")
    res, stats = client.search({}, folder="INBOX", limit=None, with_body=False,
                               with_attachments=False)
    assert len(res) == 1
    assert stats == {"candidates": 1, "scanned": 1, "truncated": False}
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
    res, stats = client.search({}, folder="INBOX", limit=1, with_body=False,
                               with_attachments=False)
    assert [r["uid"] for r in res] == ["2"]  # newest first
    assert stats["truncated"] is True and stats["reason"] == "limit"  # one candidate left over


def test_search_with_body_includes_text():
    client = ImapClient(FakeMailBox(), account_email="me@p.me")
    res, _ = client.search({}, folder="INBOX", limit=None, with_body=True,
                           with_attachments=False)
    assert res[0]["body_text"] == "We order 3 containers."


def test_list_unsubscribe_is_split_into_http_and_mailto():
    from proton_mail_bridge.core.imap import list_unsubscribe

    parsed = list_unsubscribe({
        "list-unsubscribe": ("<https://example.com/u?id=7>, <mailto:leave@example.org?subject=u>",),
        "list-unsubscribe-post": ("List-Unsubscribe=One-Click",),
    })
    assert parsed == {
        "http": ["https://example.com/u?id=7"],
        "mailto": ["mailto:leave@example.org?subject=u"],
        "one_click": True,
    }
    assert list_unsubscribe({"list-unsubscribe": ("<mailto:x@example.org>",)}) == {
        "http": [], "mailto": ["mailto:x@example.org"], "one_click": False,
    }
    assert list_unsubscribe({"message-id": ("<m@example.com>",)}) is None
    assert list_unsubscribe({}) is None


def test_summary_carries_the_unsubscribe_field_and_the_display_name():
    from tests.conftest import FakeAddress, FakeMessage

    msg = FakeMessage(uid="1", from_="news@example.org",
                      from_values=FakeAddress(name="Example News", email="news@example.org"),
                      headers={"message-id": ("<m@example.org>",),
                               "list-unsubscribe": ("<https://example.org/u>",)})
    client = ImapClient(FakeMailBox({"INBOX": [msg]}), account_email="me@p.me")
    rec = client.search({}, folder="INBOX", limit=None, with_body=False,
                        with_attachments=False)[0][0]
    assert rec["from_name"] == "Example News"
    assert rec["list_unsubscribe"]["http"] == ["https://example.org/u"]
    assert rec["list_unsubscribe"]["one_click"] is False


def test_uid_survives_the_gluon_fetch_layout():
    """Gluon puts the UID in the element *after* the literal, not before it:

        (b'2 (FLAGS (\\Seen) BODY[HEADER] {2}', b'\\r\\n')
        b' UID 3)'

    Anything scanning only the leading part for `UID (\\d+)` loses every UID silently.
    imap_tools reads both -- this pins it, because we depend on it.
    """
    from imap_tools.message import MailMessage

    raw = b"From: sender@example.com\r\nSubject: Test\r\n\r\n"
    msg = MailMessage([(b"2 (FLAGS (\\Seen) BODY[HEADER] {%d}" % len(raw), raw), b" UID 3)"])
    assert msg.uid == "3"
    assert msg.flags == ("\\Seen",)


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


def test_sender_addresses_reads_the_display_name():
    from tests.conftest import FakeAddress, FakeMessage
    named = FakeMessage(uid="1", from_="c@p.me",
                        from_values=FakeAddress(name="Chef", email="c@p.me"))
    plain = FakeMessage(uid="2", from_="k@p.me")
    mailbox = FakeMailBox({"Sent": [named, plain]})
    client = ImapClient(mailbox, account_email="me@p.me")
    assert client.sender_addresses("Sent", limit=None) == [("", "k@p.me"), ("Chef", "c@p.me")]
    assert client.sender_addresses("Sent", limit=1) == [("", "k@p.me")]  # newest first
    # headers-only (no full body fetch) and mark_seen=False (Sent stays unread-state untouched)
    for call in mailbox.fetch_calls:
        assert call["headers_only"] is True
        assert call["mark_seen"] is False
