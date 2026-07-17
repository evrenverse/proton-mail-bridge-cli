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


def test_client_filter_non_ascii_subject():
    recs = [{"subject": "Invoice Müller GmbH", "body_text": ""},
            {"subject": "Invoice Smith", "body_text": ""}]
    out = search.client_filter(recs, subject="müller")
    assert len(out) == 1
    assert out[0]["subject"] == "Invoice Müller GmbH"


def test_build_criteria_larger_smaller():
    crit = search.build_criteria(larger=10000, smaller=500000)
    assert crit["size_gt"] == 10000
    assert crit["size_lt"] == 500000


def test_build_criteria_larger_only():
    crit = search.build_criteria(larger=5000)
    assert crit["size_gt"] == 5000
    assert "size_lt" not in crit


def test_client_filter_headers_match():
    recs = [
        {"subject": "A", "headers": {"x-mailer": ["Thunderbird 91"]}},
        {"subject": "B", "headers": {"x-mailer": ["Apple Mail"]}},
        {"subject": "C", "headers": {}},
    ]
    out = search.client_filter(recs, headers=[("x-mailer", "thunderbird")])
    assert len(out) == 1
    assert out[0]["subject"] == "A"


def test_client_filter_headers_no_match():
    recs = [{"subject": "X", "headers": {"x-spam": ["no"]}}]
    out = search.client_filter(recs, headers=[("x-mailer", "outlook")])
    assert out == []
