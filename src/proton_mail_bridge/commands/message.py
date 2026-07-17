from __future__ import annotations

import click

from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import resolve_accounts
from proton_mail_bridge.core.imap import ImapClient, for_accounts
from proton_mail_bridge.utils import output as out_mod
from proton_mail_bridge.utils import search as search_mod


@click.group("message")
def message_group() -> None:
    """Read, search, and organize messages."""


def _uids(value: str) -> list[str]:
    return [u.strip() for u in value.split(",") if u.strip()]


@message_group.command("list")
@click.option("--folder", default="INBOX")
@click.option("--limit", type=int, default=50)
@click.option("--offset", type=int, default=0,
              help="Skip the first N messages (client-side slice).")
@click.option("--unread", is_flag=True)
@click.option("--since", default=None)
@click.pass_context
def list_cmd(ctx, folder, limit, offset, unread, since) -> None:
    """Header summaries of a folder, newest first (fan-out without --account)."""
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")
    crit = search_mod.build_criteria(since=since, seen=(False if unread else None))

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            recs = c.search(
                crit, folder=folder, limit=offset + limit, with_body=False, with_attachments=False
            )
            return recs[offset:offset + limit]

    out_mod.out(for_accounts(accounts, fn))


@message_group.command("search")
@click.option("--from", "from_", default=None)
@click.option("--to", default=None)
@click.option("--cc", default=None)
@click.option("--subject", default=None)
@click.option("--text", default=None)
@click.option("--since", default=None)
@click.option("--before", default=None)
@click.option("--seen/--unseen", default=None)
@click.option("--flagged", is_flag=True, default=False)
@click.option("--larger", type=int, default=None, help="Only messages larger than N bytes.")
@click.option("--smaller", type=int, default=None, help="Only messages smaller than N bytes.")
@click.option("--header", "header_filters", multiple=True,
              help="Header filter, form Key:Value (repeatable). Filtered client-side.")
@click.option("--folder", default=None, help="Folder; without it: All Mail (everything).")
@click.option("--all-folders", "all_folders", is_flag=True,
              help="Iterate over all folders (dedup).")
@click.option("--has-attachments", "has_attachments", is_flag=True,
              help="Only messages with attachments (filtered client-side).")
@click.option("--with-body", is_flag=True)
@click.option("--with-attachments", is_flag=True)
@click.option("--ids-only", "ids_only", is_flag=True,
              help="Only account/folder/uid/message_id per hit (for follow-up ops).")
@click.option("--count-only", "count_only", is_flag=True,
              help="Count only — server-side, no message fetch; ignores --limit.")
@click.option("--limit", type=int, default=50)
@click.pass_context
def search_cmd(ctx, from_, to, cc, subject, text, since, before, seen, flagged,
               larger, smaller, header_filters,
               folder, all_folders, has_attachments, with_body, with_attachments,
               ids_only, count_only, limit) -> None:
    """Bulk search, newest first. Default scope: All Mail. Body/text & non-ASCII client-side."""
    from proton_mail_bridge.core.imap import dedup_by_message_id

    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")

    # parse --header Key:Value pairs
    parsed_headers: list[tuple[str, str]] | None = None
    if header_filters:
        parsed_headers = []
        for hf in header_filters:
            if ":" in hf:
                k, _, v = hf.partition(":")
                parsed_headers.append((k.strip(), v.strip()))

    def _server(v):  # do NOT hand non-ASCII values to the server (Gluon unreliable) → client-side
        return v if v and not search_mod.is_non_ascii(v) else None

    crit = search_mod.build_criteria(
        from_=_server(from_), to=_server(to), cc=_server(cc), subject=_server(subject),
        text=None, since=since, before=before, seen=seen, flagged=flagged,
        larger=larger, smaller=smaller,
    )
    need_body = with_body or bool(text)
    # with --header, headers are filtered client-side; that requires include_headers=True
    need_headers = bool(parsed_headers)

    if count_only:
        # ponytail: counts server-side only (UID SEARCH); with client-side filters the count
        # would only be honest after a full fetch → search without --count-only instead
        if ids_only:
            out_mod.out_err("usage", "Not combinable", "--count-only excludes --ids-only")
        if text or parsed_headers or has_attachments or all_folders \
                or search_mod.is_non_ascii(from_, to, cc, subject):
            out_mod.out_err(
                "usage", "--count-only counts server-side",
                "not combinable with --text/--header/--has-attachments/--all-folders "
                "or non-ASCII values",
            )

        def fn_count(account):
            with ImapClient.connect(cfg.endpoint, account) as c:
                f = c.resolve_folder(folder, "all")
                return {"folder": f, "count": c.count(crit, f)}

        out_mod.out(for_accounts(accounts, fn_count))
        return

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            folders = c.list_folders() if all_folders else [c.resolve_folder(folder, "all")]
            recs: list[dict] = []
            for f in folders:
                recs.extend(c.search(crit, folder=f, limit=limit,
                                     with_body=need_body, with_attachments=with_attachments,
                                     include_headers=need_headers))
            recs = search_mod.client_filter(
                recs, text=text, from_=from_, to=to, cc=cc, subject=subject,
                headers=parsed_headers,
            )
            if has_attachments:
                recs = [r for r in recs if r["has_attachments"]]
            recs = dedup_by_message_id(recs)[:limit]
            if ids_only:
                recs = [{"account": r["account"], "folder": r["folder"], "uid": r["uid"],
                         "message_id": r["message_id"]} for r in recs]
            return recs

    out_mod.out(for_accounts(accounts, fn))


@message_group.command("read")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--format", "fmt", type=click.Choice(["text", "html", "both", "raw"]), default="text")
@click.option("--include-headers", is_flag=True)
@click.option("--mark-read", "mark_read", is_flag=True,
              help="Mark as read after reading.")
@click.pass_context
def read_cmd(ctx, uid, folder, fmt, include_headers, mark_read) -> None:
    """Read multiple messages by UID (bulk: --uid 1,2,3)."""
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="message_op")
    uids = _uids(uid)

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            if fmt == "raw":
                result = [
                    {"uid": u, "raw": c.fetch_raw(u, folder).decode("utf-8", "replace")}
                    for u in uids
                ]
            else:
                result = c.fetch(uids, folder=folder, fmt=fmt, include_headers=include_headers)
            if mark_read:
                c.set_flags(uids, folder=folder, add=["\\Seen"], remove=[])
            return result

    out_mod.out(for_accounts(accounts, fn))


@message_group.command("raw")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--output", type=click.Path(), default=None)
@click.pass_context
def raw_cmd(ctx, uid, folder, output) -> None:
    """Raw RFC 822 of a message."""
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="message_op")
    if len(accounts) != 1:
        out_mod.out_err(
            "account", "raw needs exactly one account", "pass --account <email|alias>"
        )
        return
    account = accounts[0]
    with ImapClient.connect(cfg.endpoint, account) as c:
        data = c.fetch_raw(uid, folder)
    if output:
        from pathlib import Path

        Path(output).write_bytes(data)
        out_mod.out_ok(f"{len(data)} bytes → {output}")
    else:
        out_mod.out({"uid": uid, "raw": data.decode("utf-8", "replace")})


def _resolve_one(ctx):
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="message_op")
    if len(accounts) != 1:
        out_mod.out_err("account", "This command needs exactly one account",
                        "pass --account <email|alias>")
    return cfg, accounts[0]


@message_group.command("move")
@click.option("--uid", required=True)
@click.option("--to", "dest", required=True)
@click.option("--folder", default="INBOX")
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def move_cmd(ctx, uid, dest, folder, assume_yes) -> None:
    """Move message(s) into a folder (🟡)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    risk = guard.escalate(guard.CONFIRM, count=len(uids))
    guard.enforce(f"message move {uids} → {dest}", risk, assume_yes=assume_yes)
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.move(uids, folder=folder, dest=dest)
    out_mod.out_ok(f"{len(uids)} moved → {dest}")


@message_group.command("copy")
@click.option("--uid", required=True)
@click.option("--to", "dest", required=True)
@click.option("--folder", default="INBOX")
@click.pass_context
def copy_cmd(ctx, uid, dest, folder) -> None:
    """Copy message(s) into a folder (🟢)."""
    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.copy(uids, folder=folder, dest=dest)
    out_mod.out_ok(f"{len(uids)} copied → {dest}")


@message_group.command("flag")
@click.option("--uid", required=True)
@click.option("--add", multiple=True)
@click.option("--remove", multiple=True)
@click.option("--folder", default="INBOX")
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def flag_cmd(ctx, uid, add, remove, folder, assume_yes) -> None:
    """Set/remove flags (🟢 add only; 🟡 with remove)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    risk = guard.escalate(guard.CONFIRM if remove else guard.FREE, count=len(uids))
    guard.enforce(f"message flag {uids}", risk, assume_yes=assume_yes)
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.set_flags(uids, folder=folder, add=list(add), remove=list(remove))
    out_mod.out_ok(f"Flags updated ({len(uids)}).")


@message_group.command("mark")
@click.option("--uid", required=True)
@click.option("--read/--unread", "read", required=True)
@click.option("--folder", default="INBOX")
@click.pass_context
def mark_cmd(ctx, uid, read, folder) -> None:
    """Mark as read/unread (🟢)."""
    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    with ImapClient.connect(cfg.endpoint, account) as c:
        add_flags = ["\\Seen"] if read else []
        remove_flags = [] if read else ["\\Seen"]
        c.set_flags(uids, folder=folder, add=add_flags, remove=remove_flags)
    out_mod.out_ok(f"{len(uids)} marked ({'read' if read else 'unread'}).")


@message_group.command("delete")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--expunge", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def delete_cmd(ctx, uid, folder, expunge, assume_yes) -> None:
    """Delete: without --expunge → Trash 🟡; --expunge / from Trash / bulk ≥ 20 → permanent 🔴."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    with ImapClient.connect(cfg.endpoint, account) as c:
        trash = c.special_folders().get("trash", "Trash")
        permanent = expunge or folder == trash
        risk = guard.CRITICAL if permanent else guard.escalate(guard.CONFIRM, count=len(uids))
        guard.enforce(f"message delete {uids} permanent={permanent}", risk,
                      assume_yes=assume_yes, token="delete")
        if permanent:
            c.delete(uids, folder=folder)
            action = "permanently deleted"
        else:
            c.move(uids, folder=folder, dest=trash)
            action = f"moved to {trash}"
    out_mod.out_ok(f"{len(uids)} {action}.")


def register(root: click.Group) -> None:
    root.add_command(message_group)
