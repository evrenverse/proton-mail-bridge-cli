from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from proton_mail_bridge.core.config import Account, Endpoint
from proton_mail_bridge.core.errors import BridgeError
from proton_mail_bridge.utils.pdftext import FIELD as ATTACHMENT_TEXT

FETCH_BATCH = 200
"""Messages per FETCH round while scanning. Keeps memory flat and lets a client-side
filter stop early instead of pulling a whole folder in one command."""


def _iso(dt: Any) -> str | None:
    try:
        return dt.isoformat()
    except AttributeError:
        return None


def _header(headers: dict, name: str) -> str:
    """First value of a header; imap_tools lowercases the keys."""
    values = (headers or {}).get(name.lower()) or (headers or {}).get(name) or ()
    if isinstance(values, str):
        return values
    return str(values[0]) if values else ""


def list_unsubscribe(headers: dict) -> dict | None:
    """RFC 2369 `List-Unsubscribe` split into http/mailto targets, plus the RFC 8058
    one-click flag from `List-Unsubscribe-Post`. None when the header is absent.

    Presence is a bulk-sender signal, not a verdict: project and portal notifications set
    it too. Use it to select candidates, never as an automatic delete recommendation.
    """
    raw = _header(headers, "list-unsubscribe")
    if not raw:
        return None
    targets = [t.strip() for t in re.findall(r"<([^>]+)>", raw)]
    post = _header(headers, "list-unsubscribe-post").lower()
    return {
        "http": [t for t in targets if t.lower().startswith("http")],
        "mailto": [t for t in targets if t.lower().startswith("mailto:")],
        "one_click": "one-click" in post,
    }


def attachment_meta(att: Any) -> dict:
    return {
        "filename": att.filename,
        "content_type": att.content_type,
        "size": att.size,
        "content_id": att.content_id,
        "inline": getattr(att, "content_disposition", "") == "inline",
    }


def summarize(msg: Any, account_email: str, folder: str) -> dict:
    atts = list(msg.attachments or [])
    headers = msg.headers or {}
    real_msgid = ""
    mid = headers.get("message-id")
    if mid:
        real_msgid = mid[0] if isinstance(mid, (list, tuple)) else str(mid)
    return {
        "account": account_email,
        "uid": msg.uid,
        "folder": folder,
        "message_id": real_msgid,
        "date": _iso(msg.date),
        "date_str": msg.date_str,
        "from": msg.from_,
        "from_name": getattr(getattr(msg, "from_values", None), "name", "") or "",
        "list_unsubscribe": list_unsubscribe(headers),
        "to": list(msg.to),
        "cc": list(msg.cc),
        "subject": msg.subject,
        "flags": list(msg.flags),
        "size": msg.size,
        "has_attachments": bool(atts),
        "attachment_count": len(atts),
        "snippet": (msg.text or "")[:200],
    }


def full_message(
    msg: Any, account_email: str, folder: str, fmt: str, include_headers: bool
) -> dict:
    data = summarize(msg, account_email, folder)
    if fmt in ("text", "both"):
        data["body_text"] = msg.text
    if fmt in ("html", "both"):
        data["body_html"] = msg.html
    data["attachments"] = [attachment_meta(a) for a in (msg.attachments or [])]
    if include_headers:
        data["headers"] = {k: list(v) for k, v in (msg.headers or {}).items()}
    return data


class ImapClient:
    """Click-independent IMAP wrapper. One instance = one account."""

    def __init__(self, mailbox: Any, account_email: str):
        self._mb = mailbox
        self._email = account_email
        self._special: dict[str, str] | None = None

    @classmethod
    def connect(
        cls, endpoint: Endpoint, account: Account, *, host: str | None = None
    ) -> ImapClient:
        from imap_tools import MailBox, MailBoxStartTls

        from proton_mail_bridge.core.connection import resolve_host, tls_context

        host = host or resolve_host(endpoint)[0]
        ctx = tls_context(endpoint)
        mb: MailBox
        if endpoint.security == "ssl":
            mb = MailBox(host, endpoint.imap_port, timeout=endpoint.timeout, ssl_context=ctx)
        else:
            mb = MailBoxStartTls(host, endpoint.imap_port, timeout=endpoint.timeout,
                                 ssl_context=ctx)  # type: ignore[assignment]
        mb.login(account.email, account.password)
        return cls(mb, account.email)

    def __enter__(self) -> ImapClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self._mb.logout()
        except Exception:
            pass

    def list_folders(self) -> list[str]:
        return [f.name for f in self._mb.folder.list()]

    def folder_status(self, name: str) -> dict:
        return dict(self._mb.folder.status(name))

    def _criteria(self, criteria: dict) -> Any:
        from imap_tools import AND

        return AND(**criteria) if criteria else "ALL"

    def _uid_list(self, criteria: dict, folder: str) -> list[str]:
        """The server-side match set as a stable snapshot, newest first.

        UID order is arrival order; taking the list once (instead of re-running SEARCH per
        page) keeps paging stable while mail keeps coming in.
        """
        self._mb.folder.set(folder)
        return list(reversed(self._mb.uids(self._criteria(criteria))))

    @staticmethod
    def _room(max_fetch: int | None, stats: dict) -> int:
        """Messages the next round may fetch. Without this the budget is rounded up to the
        batch size, and `--max-fetch 50` reads 200."""
        if not max_fetch:
            return FETCH_BATCH
        return min(FETCH_BATCH, max_fetch - stats["scanned"])

    def _record(self, msg: Any, folder: str, *, with_body: bool, with_attachments: bool,
                include_headers: bool, with_attachment_text: bool = False) -> dict:
        if with_body or include_headers:
            fmt = "both" if with_body else "none"
            rec = full_message(msg, self._email, folder, fmt, include_headers=include_headers)
        else:
            rec = summarize(msg, self._email, folder)
            if with_attachments:
                rec["attachments"] = [attachment_meta(a) for a in (msg.attachments or [])]
        if with_attachment_text:
            from proton_mail_bridge.utils import pdftext

            rec[ATTACHMENT_TEXT] = "\n".join(
                pdftext.extract(a.payload or b"") for a in (msg.attachments or [])
            )
        return rec

    def _materialize(self, uids: list[str], folder: str, *, with_body: bool = False,
                     with_attachments: bool = False, include_headers: bool = False,
                     with_attachment_text: bool = False,
                     headers_only: bool = False) -> Iterator[dict]:
        """Records for an explicit UID list, newest first, in FETCH_BATCH-sized rounds.

        `headers_only` fetches BODY.PEEK[HEADER]: no body transfer, no `\\Seen` side effect —
        enough for header/date/subject filters, not for body text or attachments.
        """
        from imap_tools import AND

        self._mb.folder.set(folder)
        for start in range(0, len(uids), FETCH_BATCH):
            chunk = uids[start:start + FETCH_BATCH]
            msgs = self._mb.fetch(AND(uid=",".join(chunk)), mark_seen=False, bulk=True,
                                  reverse=True, headers_only=headers_only)
            for m in msgs:
                yield self._record(m, folder, with_body=with_body,
                                   with_attachments=with_attachments,
                                   include_headers=include_headers,
                                   with_attachment_text=with_attachment_text)

    def search(self, criteria: dict, folder: str, limit: int | None,
               with_body: bool, with_attachments: bool,
               include_headers: bool = False,
               keep: Callable[[dict], bool] | None = None,
               scan_needs_body: bool = False,
               with_attachment_text: bool = False,
               max_fetch: int | None = None) -> tuple[list[dict], dict]:
        """Search a folder, newest first. Returns (records, stats).

        `keep` is the client-side predicate for everything the server cannot decide (body
        text, non-ASCII, headers, attachments). It runs *while* paging, so `limit` bounds the
        MATCHES, not the messages fetched — a filtered search keeps reading until it has
        enough hits or the folder is exhausted.

        `max_fetch` caps the scan; an exhausted budget (or a `limit` reached with candidates
        left over) shows up as `truncated` in the stats. Nothing is ever cut silently.
        """
        uids = self._uid_list(criteria, folder)
        stats: dict[str, Any] = {"candidates": len(uids), "scanned": 0, "truncated": False}
        opts = {"with_body": with_body, "with_attachments": with_attachments,
                "include_headers": include_headers,
                "with_attachment_text": with_attachment_text}

        if keep is None:
            # nothing to filter client-side: the server already decided, the window is exact
            window = uids[:limit] if limit else uids
            recs = list(self._materialize(window, folder, **opts))
            stats["scanned"] = len(recs)
            if len(window) < len(uids):
                stats.update(truncated=True, reason="limit")
            return recs, stats

        # header-only scan whenever the predicate does not need body or attachments:
        # scanning 30k headers is a different order of cost than scanning 30k bodies
        headers_only = not scan_needs_body
        scan_opts = ({"with_body": False, "with_attachments": False, "include_headers": True,
                      "with_attachment_text": False, "headers_only": True}
                     if headers_only else opts)
        matched: list[dict] = []
        reason = ""
        pos = 0
        while pos < len(uids):
            if limit is not None and len(matched) >= limit:
                reason = "limit"
                break
            if max_fetch and stats["scanned"] >= max_fetch:
                reason = "fetch_budget"
                break
            chunk = uids[pos:pos + self._room(max_fetch, stats)]
            pos += len(chunk)
            for rec in self._materialize(chunk, folder, **scan_opts):
                stats["scanned"] += 1
                if keep(rec):
                    matched.append(rec)
        if limit is not None and len(matched) > limit:
            matched = matched[:limit]
            reason = reason or "limit"
        if reason:
            stats.update(truncated=True, reason=reason)
        if headers_only:  # the survivors get fetched properly (body, attachments, size)
            matched = list(self._materialize([r["uid"] for r in matched], folder,
                                             **opts))
        for rec in matched:  # scratch space for the predicate, never part of the result
            rec.pop(ATTACHMENT_TEXT, None)
        return matched, stats

    def count(self, criteria: dict, folder: str) -> int:
        """Server-side count via UID SEARCH — no message fetch."""
        self._mb.folder.set(folder)
        return len(self._mb.uids(self._criteria(criteria)))

    def sender_stats(self, criteria: dict, folder: str,
                     max_fetch: int | None = None) -> tuple[list[dict], dict]:
        """Count per From address over the whole scope — headers only, no body fetch.

        Aggregating in the CLI breaks the raw-data principle on purpose: the alternative is
        shipping 30k records to the caller just to group them.
        """
        uids = self._uid_list(criteria, folder)
        stats: dict[str, Any] = {"candidates": len(uids), "scanned": 0, "truncated": False}
        agg: dict[str, dict] = {}
        pos = 0
        while pos < len(uids):
            if max_fetch and stats["scanned"] >= max_fetch:
                stats.update(truncated=True, reason="fetch_budget")
                break
            chunk = uids[pos:pos + self._room(max_fetch, stats)]
            pos += len(chunk)
            for rec in self._materialize(chunk, folder, headers_only=True):
                stats["scanned"] += 1
                key = (rec["from"] or "").lower()
                entry = agg.get(key)
                if entry is None:  # newest first → the first hit is the most recent mail
                    agg[key] = {
                        "from": rec["from"], "name": rec["from_name"], "count": 1,
                        "last_date": rec["date"], "last_subject": rec["subject"],
                        "list_unsubscribe": bool(rec["list_unsubscribe"]),
                    }
                    continue
                entry["count"] += 1
                entry["name"] = entry["name"] or rec["from_name"]
                entry["list_unsubscribe"] = entry["list_unsubscribe"] or bool(
                    rec["list_unsubscribe"]
                )
        return list(agg.values()), stats

    def sender_addresses(self, folder: str, limit: int | None) -> list[tuple[str, str]]:
        """(display name, From address) per message — headers only, no body fetch."""
        self._mb.folder.set(folder)
        msgs = self._mb.fetch("ALL", limit=limit, mark_seen=False, bulk=True, reverse=True,
                              headers_only=True)
        out: list[tuple[str, str]] = []
        for m in msgs:
            values = getattr(m, "from_values", None)
            out.append((getattr(values, "name", "") or "", m.from_))
        return out

    def create_folder(self, name: str) -> None:
        self._mb.folder.create(name)

    def fetch(self, uids: list[str], folder: str, fmt: str, include_headers: bool) -> list[dict]:
        from imap_tools import AND

        self._mb.folder.set(folder)
        msgs = self._mb.fetch(AND(uid=",".join(uids)), mark_seen=False, bulk=True)
        return [full_message(m, self._email, folder, fmt, include_headers) for m in msgs]

    def preview(self, uids: list[str], folder: str) -> list[dict]:
        """Headers of the given UIDs — for dry runs. `headers_only` + `mark_seen=False`
        means BODY.PEEK[HEADER]: no body transfer and, above all, no `\\Seen` side effect.
        UIDs the server does not know simply do not come back (caller reports them)."""
        from imap_tools import AND

        if not uids:
            return []
        self._mb.folder.set(folder)
        msgs = self._mb.fetch(AND(uid=",".join(uids)), mark_seen=False, bulk=True,
                              headers_only=True)
        return [
            {
                "uid": m.uid,
                "folder": folder,
                "date": _iso(m.date),
                "from": m.from_,
                "subject": m.subject,
                "size": m.size,
                "flags": list(m.flags),
            }
            for m in msgs
        ]

    def fetch_raw(self, uid: str, folder: str) -> bytes:
        from imap_tools import AND

        self._mb.folder.set(folder)
        for m in self._mb.fetch(AND(uid=uid), mark_seen=False, bulk=True):
            return m.obj.as_bytes()
        return b""

    def move(self, uids: list[str], folder: str, dest: str) -> None:
        self._mb.folder.set(folder)
        self._mb.move(uids, dest)

    def copy(self, uids: list[str], folder: str, dest: str) -> None:
        self._mb.folder.set(folder)
        self._mb.copy(uids, dest)

    def set_flags(self, uids: list[str], folder: str, add: list[str], remove: list[str]) -> None:
        self._mb.folder.set(folder)
        if add:
            self._mb.flag(uids, add, True)
        if remove:
            self._mb.flag(uids, remove, False)

    def delete(self, uids: list[str], folder: str) -> None:
        """Permanent delete (\\Deleted + immediate expunge). The soft delete
        (move to Trash) is done by the command layer via move()."""
        self._mb.folder.set(folder)
        self._mb.delete(uids)

    def append(self, raw: bytes, folder: str, flags: list[str] | None = None) -> None:
        self._mb.append(raw, folder, flag_set=flags)

    def attachments(self, uid: str, folder: str) -> list[Any]:
        from imap_tools import AND

        self._mb.folder.set(folder)
        for m in self._mb.fetch(AND(uid=uid), mark_seen=False, bulk=True):
            return list(m.attachments or [])
        return []

    def special_folders(self) -> dict[str, str]:
        """Logical name (all/sent/drafts/trash/junk/archive/flagged) → real folder name
        via RFC 6154 special-use flags (language-independent; Proton names are
        localized). Cached per instance — one LIST per connection is enough."""
        if self._special is None:
            result: dict[str, str] = {}
            for f in self._mb.folder.list():
                flags = {str(x).lower() for x in (f.flags or ())}
                for key, attr in SPECIAL_USE.items():
                    if attr.lower() in flags:
                        result[key] = f.name
            self._special = result
        return self._special

    def is_all_mail(self, folder: str) -> bool:
        return folder == self.special_folders().get("all", ALL_MAIL_FALLBACK)

    def ensure_writable(self, folder: str, what: str) -> None:
        """All Mail is a virtual view over every other folder: the Bridge rejects writes to
        it, and a mail 'removed' there would still sit in its real folder. Say so instead of
        letting the server refuse it in its own words."""
        if self.is_all_mail(folder):
            raise BridgeError(
                "read_only",
                f"{folder} is read-only",
                f"{what} cannot run in {folder} — it is a duplicate view over every other "
                "folder. Work folder by folder instead (message search --all-folders "
                "--ids-only, or message bulk-move/bulk-delete, which skip it).",
            )

    def resolve_folder(self, folder: str | None, default_special: str = "all") -> str:
        """`folder` if set; otherwise the special-use default (e.g. 'all' → 'All Mail'),
        fallback INBOX."""
        if folder:
            return folder
        return self.special_folders().get(default_special, "INBOX")


SPECIAL_USE = {
    "all": "\\All", "sent": "\\Sent", "drafts": "\\Drafts", "trash": "\\Trash",
    "junk": "\\Junk", "archive": "\\Archive", "flagged": "\\Flagged",
}

ALL_MAIL_FALLBACK = "All Mail"


def for_accounts(accounts: list[Account], fn: Callable[[Account], Any]) -> list[dict]:
    """Runs fn per account; fault-tolerant, tags every result with 'account'.

    `fn` may return `(items, extra)`; `extra` is merged next to `items` (search stats etc.).
    """
    results: list[dict] = []
    for account in accounts:
        try:
            items = fn(account)
            extra: dict = {}
            if isinstance(items, tuple):
                items, extra = items
            results.append({"account": account.email, "ok": True, **extra, "items": items})
        except Exception as exc:  # one broken account must not kill the whole run
            results.append({
                "account": account.email, "ok": False,
                "error": {"type": "account", "title": "Account failed", "detail": str(exc)},
            })
    return results


def dedup_by_message_id(records: list[dict]) -> list[dict]:
    """Mandatory for multi-folder search: the same mail lives in INBOX + Labels/X + All Mail
    (each with its own UID, same Message-ID). Fallback key if the Message-ID is empty."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in records:
        key = r.get("message_id") or f"{r.get('account')}:{r.get('folder')}:{r.get('uid')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
