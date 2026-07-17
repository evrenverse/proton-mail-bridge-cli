from __future__ import annotations

from collections.abc import Callable
from typing import Any

from proton_mail_bridge.core.config import Account, Endpoint


def _iso(dt: Any) -> str | None:
    try:
        return dt.isoformat()
    except AttributeError:
        return None


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
    real_msgid = ""
    mid = (msg.headers or {}).get("message-id")
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

    def search(self, criteria: dict, folder: str, limit: int | None,
               with_body: bool, with_attachments: bool,
               include_headers: bool = False) -> list[dict]:
        self._mb.folder.set(folder)
        msgs = self._mb.fetch(self._criteria(criteria), limit=limit, mark_seen=False, bulk=True,
                              reverse=True)  # newest first; limit applies after reversing
        out: list[dict] = []
        for m in msgs:
            if with_body or include_headers:
                rec = full_message(m, self._email, folder, "both", include_headers=include_headers)
            else:
                rec = summarize(m, self._email, folder)
                if with_attachments:
                    rec["attachments"] = [attachment_meta(a) for a in (m.attachments or [])]
            out.append(rec)
        return out

    def count(self, criteria: dict, folder: str) -> int:
        """Server-side count via UID SEARCH — no message fetch."""
        self._mb.folder.set(folder)
        return len(self._mb.uids(self._criteria(criteria)))

    def create_folder(self, name: str) -> None:
        self._mb.folder.create(name)

    def fetch(self, uids: list[str], folder: str, fmt: str, include_headers: bool) -> list[dict]:
        from imap_tools import AND

        self._mb.folder.set(folder)
        msgs = self._mb.fetch(AND(uid=",".join(uids)), mark_seen=False, bulk=True)
        return [full_message(m, self._email, folder, fmt, include_headers) for m in msgs]

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
        localized)."""
        result: dict[str, str] = {}
        for f in self._mb.folder.list():
            flags = {str(x).lower() for x in (f.flags or ())}
            for key, attr in SPECIAL_USE.items():
                if attr.lower() in flags:
                    result[key] = f.name
        return result

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


def for_accounts(accounts: list[Account], fn: Callable[[Account], Any]) -> list[dict]:
    """Runs fn per account; fault-tolerant, tags every result with 'account'."""
    results: list[dict] = []
    for account in accounts:
        try:
            results.append({"account": account.email, "ok": True, "items": fn(account)})
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
