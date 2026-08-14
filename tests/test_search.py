from __future__ import annotations

from proton_mail_bridge.utils import search


def test_build_criteria_maps_flags():
    crit = search.build_criteria(from_="x@y.de", subject="Invoice", text=None,
                                 since="2026-01-01", before=None, seen=True)
    assert crit["from_"] == "x@y.de"
    assert crit["subject"] == "Invoice"
    assert crit["seen"] is True
    assert str(crit["date_gte"]) == "2026-01-01"


def test_is_non_ascii():
    assert search.is_non_ascii("Müller") is True   # umlaut → filter client-side
    assert search.is_non_ascii("Invoice") is False
    assert search.is_non_ascii(None) is False


def test_predicate_non_ascii_subject():
    recs = [{"subject": "Invoice Müller GmbH", "body_text": ""},
            {"subject": "Invoice Smith", "body_text": ""}]
    out = [r for r in recs if search.predicate(subject="müller")(r)]
    assert len(out) == 1
    assert out[0]["subject"] == "Invoice Müller GmbH"


def test_predicate_is_none_when_the_server_decides_alone():
    """None is the signal that --limit already describes the result exactly — no scan needed."""
    assert search.predicate(subject="Invoice", from_="a@example.com") is None
    assert search.predicate() is None
    assert search.predicate(text="invoice") is not None
    assert search.predicate(has_attachments=True) is not None
    assert search.predicate(list_unsubscribe=True) is not None
    assert search.predicate(headers=[("x-mailer", "thunderbird")]) is not None
    assert search.predicate(subject="Müller") is not None  # non-ASCII → client-side


def test_build_criteria_larger_smaller():
    crit = search.build_criteria(larger=10000, smaller=500000)
    assert crit["size_gt"] == 10000
    assert crit["size_lt"] == 500000


def test_build_criteria_larger_only():
    crit = search.build_criteria(larger=5000)
    assert crit["size_gt"] == 5000
    assert "size_lt" not in crit


def test_predicate_headers_match():
    recs = [
        {"subject": "A", "headers": {"x-mailer": ["Thunderbird 91"]}},
        {"subject": "B", "headers": {"x-mailer": ["Apple Mail"]}},
        {"subject": "C", "headers": {}},
    ]
    keep = search.predicate(headers=[("x-mailer", "thunderbird")])
    out = [r for r in recs if keep(r)]
    assert len(out) == 1
    assert out[0]["subject"] == "A"


def test_predicate_headers_no_match():
    keep = search.predicate(headers=[("x-mailer", "outlook")])
    assert keep({"subject": "X", "headers": {"x-spam": ["no"]}}) is False


def test_predicate_list_unsubscribe_and_attachments():
    keep = search.predicate(list_unsubscribe=True)
    assert keep({"list_unsubscribe": {"http": ["https://example.com/u"]}}) is True
    assert keep({"list_unsubscribe": None}) is False
    assert search.predicate(has_attachments=True)({"has_attachments": False}) is False
