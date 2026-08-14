"""`--limit` bounds the matches, not the fetch window.

The bug this pins: client-side criteria (`--header`, `--text`, `--has-attachments`, non-ASCII
values) used to run *after* `--limit` had already cut the fetch. The same search then answered
`--limit 50` with 7 hits and `--limit 2000` with 111 -- plausible, incomplete, and silent
about it.
"""
from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox, FakeMessage

BULK_HEADER = "bulk"


def _msg(i: int, *, bulk: bool = False, subject: str | None = None) -> FakeMessage:
    headers: dict = {"message-id": (f"<m{i}@example.com>",)}
    if bulk:
        headers["x-campaign"] = (BULK_HEADER,)
    return FakeMessage(uid=str(i), subject=subject or f"Message {i}",
                       from_=f"sender{i}@example.com", headers=headers, attachments=[])


def _cli(monkeypatch, store: dict) -> FakeMailBox:
    mb = FakeMailBox(store)
    monkeypatch.setattr(cfgmod, "resolve_config",
                        lambda *a, **k: Config(Endpoint(), [Account("a@p.me", "pw")], "a@p.me"))
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email))
    )
    return mb


def _run(args: list[str]) -> dict:
    result = CliRunner().invoke(main, ["--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)[0]


def test_client_side_filter_sees_the_whole_folder_not_the_limit_window(monkeypatch):
    """500 messages, the 3 oldest are the only hits -- they sit far outside any small window."""
    store = {"INBOX": [_msg(i, bulk=i <= 3) for i in range(1, 501)]}
    _cli(monkeypatch, store)

    small = _run(["message", "search", "--folder", "INBOX", "--header", "X-Campaign:bulk",
                  "--limit", "50"])
    large = _run(["message", "search", "--folder", "INBOX", "--header", "X-Campaign:bulk",
                  "--limit", "2000"])

    assert [r["uid"] for r in small["items"]] == ["3", "2", "1"]
    assert [r["uid"] for r in large["items"]] == ["3", "2", "1"]  # --limit changes nothing
    assert small["search"]["scanned"] == 500        # kept reading until the folder was done
    assert small["search"]["candidates"] == 500
    assert small["search"]["truncated"] is False    # complete answer, and it says so


def test_limit_caps_the_matches_and_reports_the_cut(monkeypatch):
    """Every message matches: the limit is honest work, but it must not look complete."""
    _cli(monkeypatch, {"INBOX": [_msg(i, bulk=True) for i in range(1, 61)]})
    data = _run(["message", "search", "--folder", "INBOX", "--header", "X-Campaign:bulk",
                 "--limit", "5"])
    assert len(data["items"]) == 5
    assert data["items"][0]["uid"] == "60"          # newest first
    assert data["search"]["truncated"] is True
    assert data["search"]["reason"] == "limit"


def test_exhausted_fetch_budget_is_reported(monkeypatch):
    """A budget is allowed to cut the scan -- silently is not."""
    _cli(monkeypatch, {"INBOX": [_msg(i, bulk=i <= 3) for i in range(1, 501)]})
    data = _run(["message", "search", "--folder", "INBOX", "--header", "X-Campaign:bulk",
                 "--max-fetch", "200"])
    assert data["items"] == []                      # the hits sit beyond the budget
    assert data["search"]["scanned"] == 200
    assert data["search"]["truncated"] is True
    assert data["search"]["reason"] == "fetch_budget"


def test_fetch_budget_is_exact_not_rounded_up_to_the_batch(monkeypatch):
    """Observed live: --max-fetch 50 read 200, because the budget was only checked between
    rounds. A budget that quietly costs four times what it says is the wrong kind of cap."""
    _cli(monkeypatch, {"INBOX": [_msg(i, bulk=i <= 3) for i in range(1, 501)]})
    for budget in ("50", "137"):
        data = _run(["message", "search", "--folder", "INBOX", "--header", "X-Campaign:bulk",
                     "--max-fetch", budget])
        assert data["search"]["scanned"] == int(budget)
        assert data["search"]["reason"] == "fetch_budget"


def test_unfiltered_search_reports_a_complete_window(monkeypatch):
    """Without a client-side filter the server decides -- `truncated` then only means paging."""
    _cli(monkeypatch, {"INBOX": [_msg(i) for i in range(1, 11)]})
    exact = _run(["message", "search", "--folder", "INBOX", "--limit", "0"])
    assert len(exact["items"]) == 10
    assert exact["search"]["truncated"] is False
    window = _run(["message", "search", "--folder", "INBOX", "--limit", "4"])
    assert window["search"]["truncated"] is True and window["search"]["reason"] == "limit"


def test_filtered_scan_reads_headers_only_then_fetches_the_hits(monkeypatch):
    """Scanning 30k bodies to answer a header question is the difference between usable and not."""
    mb = _cli(monkeypatch, {"INBOX": [_msg(i, bulk=i == 1) for i in range(1, 6)]})
    data = _run(["message", "search", "--folder", "INBOX", "--header", "X-Campaign:bulk"])
    assert [r["uid"] for r in data["items"]] == ["1"]
    scan, materialize = mb.fetch_calls[0], mb.fetch_calls[-1]
    assert scan["headers_only"] is True             # scan: BODY.PEEK[HEADER]
    assert materialize["headers_only"] is False     # only the survivors get fetched fully
    assert all(c["mark_seen"] is False for c in mb.fetch_calls)


def test_text_search_scans_bodies_because_headers_cannot_answer_it(monkeypatch):
    store = {"INBOX": [_msg(1), _msg(2)]}
    store["INBOX"][1].text = "please send the invoice"
    _cli(monkeypatch, store)
    data = _run(["message", "search", "--folder", "INBOX", "--text", "invoice"])
    assert [r["uid"] for r in data["items"]] == ["2"]
    assert data["search"]["scanned"] == 2


def test_count_only_scans_client_side_criteria_instead_of_guessing(monkeypatch):
    """A count over a window is worse than no count. It used to be refused; now it scans --
    and `--limit` must not move the number, or it would be a window count again."""
    _cli(monkeypatch, {"INBOX": [_msg(i, bulk=i <= 3) for i in range(1, 501)]})
    for limit in ("5", "50", "0"):
        data = _run(["message", "search", "--count-only", "--folder", "INBOX",
                     "--header", "X-Campaign:bulk", "--limit", limit])["items"]
        assert data["count"] == 3
        assert data["scanned"] == 500
        assert data["truncated"] is False


def test_count_only_reports_a_count_cut_short_by_the_budget(monkeypatch):
    """An incomplete count has to be recognizable as incomplete."""
    _cli(monkeypatch, {"INBOX": [_msg(i, bulk=i <= 3) for i in range(1, 501)]})
    data = _run(["message", "search", "--count-only", "--folder", "INBOX",
                 "--header", "X-Campaign:bulk", "--max-fetch", "100"])["items"]
    assert data["count"] == 0            # the hits sit beyond the budget
    assert data["scanned"] == 100
    assert data["truncated"] is True and data["reason"] == "fetch_budget"


def test_count_only_without_client_criteria_stays_server_side(monkeypatch):
    mb = _cli(monkeypatch, {"INBOX": [_msg(i) for i in range(1, 6)]})
    data = _run(["message", "search", "--count-only", "--folder", "INBOX"])["items"]
    assert data == {"folder": "INBOX", "count": 5}
    assert mb.fetch_calls == []          # UID SEARCH only, not a single message fetched


def test_count_only_refuses_all_folders(monkeypatch):
    """Counting folder by folder would count a labelled mail once per label."""
    _cli(monkeypatch, {"INBOX": [_msg(1)]})
    result = CliRunner().invoke(main, ["--json", "message", "search", "--count-only",
                                       "--all-folders"])
    assert result.exit_code != 0
    assert json.loads(result.output)["error"]["type"] == "usage"


def test_all_folders_asks_each_folder_only_for_what_is_still_missing(monkeypatch):
    """With 35 folders, asking every one for the full --limit fetches an order of magnitude
    more than the answer needs -- and the surplus is thrown away after deduplication."""
    mb = _cli(monkeypatch, {
        "INBOX": [_msg(i, bulk=True) for i in range(1, 101)],
        "Archive": [_msg(i, bulk=True) for i in range(200, 300)],
        "Sent": [_msg(i, bulk=True) for i in range(400, 500)],
    })
    data = _run(["message", "search", "--all-folders", "--header", "X-Campaign:bulk",
                 "--limit", "10", "--ids-only"])
    assert len(data["items"]) == 10
    assert {c["folder"] for c in mb.fetch_calls} == {"INBOX"}   # the rest stayed untouched
    assert data["search"]["truncated"] is True
    assert data["search"]["reason"] == "limit"


def test_all_folders_fills_the_limit_from_later_folders(monkeypatch):
    """The budget shrinks per folder, but the limit still has to be filled while matches
    are left -- otherwise the shortcut would quietly return too few."""
    mb = _cli(monkeypatch, {
        "INBOX": [_msg(1, bulk=True), _msg(2, bulk=True)],
        "Archive": [_msg(i, bulk=True) for i in range(10, 30)],
    })
    data = _run(["message", "search", "--all-folders", "--header", "X-Campaign:bulk",
                 "--limit", "5", "--ids-only"])
    assert len(data["items"]) == 5
    assert {c["folder"] for c in mb.fetch_calls} == {"INBOX", "Archive"}


def test_all_folders_deduplicates_across_folders_without_losing_hits(monkeypatch):
    """All Mail holds a copy of everything: the duplicates must not eat the limit."""
    inbox = [_msg(i, bulk=True) for i in range(1, 4)]
    allmail = [_msg(i, bulk=True) for i in range(1, 4)]
    for real, copy in zip(inbox, allmail, strict=True):
        copy.uid = str(int(real.uid) + 900)            # own UID, same Message-ID
    _cli(monkeypatch, {"INBOX": inbox, "All Mail": allmail})
    data = _run(["message", "search", "--all-folders", "--header", "X-Campaign:bulk",
                 "--limit", "0", "--ids-only"])
    assert [r["uid"] for r in data["items"]] == ["3", "2", "1"]   # each mail exactly once
    assert data["search"]["truncated"] is False
