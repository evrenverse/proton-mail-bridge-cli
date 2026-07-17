from __future__ import annotations

import datetime as _dt


def _date(value: str | None):
    if not value:
        return None
    return _dt.date.fromisoformat(value)


def build_criteria(*, from_=None, to=None, cc=None, subject=None, text=None,
                   since=None, before=None, seen=None, flagged=None,
                   larger: int | None = None, smaller: int | None = None) -> dict:
    """Builds an imap_tools.AND(**kwargs)-compatible dict from CLI options.

    larger/smaller: size filters in bytes → imap_tools AND kwargs size_gt/size_lt.
    """
    crit: dict = {}
    if from_:
        crit["from_"] = from_
    if to:
        crit["to"] = to
    if cc:
        crit["cc"] = cc
    if subject:
        crit["subject"] = subject
    if text:
        crit["text"] = text
    if since:
        crit["date_gte"] = _date(since)
    if before:
        crit["date_lt"] = _date(before)
    if seen is True:
        crit["seen"] = True
    if seen is False:
        crit["seen"] = False
    if flagged:
        crit["flagged"] = True
    if larger is not None:
        crit["size_gt"] = larger
    if smaller is not None:
        crit["size_lt"] = smaller
    return crit


def is_non_ascii(*values: str | None) -> bool:
    return any(v and any(ord(ch) > 127 for ch in v) for v in values)


def client_filter(
    records: list[dict], *, text=None, from_=None, to=None, cc=None, subject=None,
    headers: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """Client-side filter for everything Gluon handles unreliably server-side:
    body/text, non-ASCII values, and header matches (case-insensitive substring).

    headers: (key, value) pairs from --header; requires records with a "headers" field
    (search() with include_headers=True).
    """
    def matches(r: dict) -> bool:
        if text:
            n = text.lower()
            hay = " ".join([
                r.get("subject", "") or "",
                r.get("body_text", "") or "",
                r.get("body_html", "") or "",
            ]).lower()
            if n not in hay:
                return False
        if subject and is_non_ascii(subject) and subject.lower() not in (
            r.get("subject", "") or ""
        ).lower():
            return False
        if from_ and is_non_ascii(from_) and from_.lower() not in (
            str(r.get("from", "")) or ""
        ).lower():
            return False
        for field, val in (("to", to), ("cc", cc)):
            if val and is_non_ascii(val) and val.lower() not in (
                ",".join(r.get(field, []) or [])
            ).lower():
                return False
        if headers:
            rec_headers: dict = r.get("headers") or {}
            for hkey, hval in headers:
                # values in the headers dict are lists; case-insensitive substring match
                raw_vals = rec_headers.get(hkey.lower(), rec_headers.get(hkey, []))
                vals_list = raw_vals if isinstance(raw_vals, (list, tuple)) else [raw_vals]
                combined = ",".join(str(v) for v in vals_list)
                if hval.lower() not in combined.lower():
                    return False
        return True

    return [r for r in records if matches(r)]
