from __future__ import annotations

from proton_mail_bridge.core.config import Account
from proton_mail_bridge.core.imap import dedup_by_message_id, for_accounts


def test_fanout_tags_results_and_tolerates_errors():
    accounts = [Account("a@p.me", "1"), Account("b@p.me", "2")]

    def fn(account):
        if account.email == "b@p.me":
            raise RuntimeError("boom")
        return [{"uid": "1"}]

    results = for_accounts(accounts, fn)
    by_acc = {r["account"]: r for r in results}
    assert by_acc["a@p.me"]["ok"] is True
    assert by_acc["a@p.me"]["items"] == [{"uid": "1"}]
    assert by_acc["b@p.me"]["ok"] is False
    assert "boom" in by_acc["b@p.me"]["error"]["detail"]


def test_dedup_by_message_id_collapses_label_copies():
    records = [
        {"message_id": "<m1@x>", "folder": "INBOX", "uid": "1"},
        # gleiche Mail, anderes Label
        {"message_id": "<m1@x>", "folder": "Labels/Work", "uid": "9"},
        {"message_id": "<m2@x>", "folder": "INBOX", "uid": "2"},
    ]
    out = dedup_by_message_id(records)
    assert [r["message_id"] for r in out] == ["<m1@x>", "<m2@x>"]
