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


def _cap(limit: int | None) -> int | None:
    """`--limit 0` (and None) mean: no cap, return every match."""
    return limit if limit else None


# Selection criteria shared by `search`, `bulk-move` and `bulk-delete` — one definition, so a
# bulk operation selects exactly what the same options would have found in a search.
SELECT_OPTS = [
    click.option("--from", "from_", default=None),
    click.option("--to", default=None, help="Recipient filter (bulk: the destination is --dest)."),
    click.option("--cc", default=None),
    click.option("--subject", default=None),
    click.option("--text", default=None, help="Body text; filtered client-side (fetches bodies)."),
    click.option("--since", default=None),
    click.option("--before", default=None),
    click.option("--seen/--unseen", default=None),
    click.option("--flagged", is_flag=True, default=False),
    click.option("--larger", type=int, default=None, help="Only messages larger than N bytes."),
    click.option("--smaller", type=int, default=None, help="Only messages smaller than N bytes."),
    click.option("--header", "header_filters", multiple=True,
                 help="Header filter, form Key:Value (repeatable). Filtered client-side."),
    click.option("--has-attachments", "has_attachments", is_flag=True,
                 help="Only messages with attachments (filtered client-side)."),
    click.option("--list-unsubscribe", "list_unsub", is_flag=True,
                 help="Only messages carrying List-Unsubscribe (RFC 2369). A selection "
                      "criterion, not a verdict: project and portal notifications set the "
                      "header too, so this is never a reason to delete on its own."),
]


def select_options(fn):
    for opt in reversed(SELECT_OPTS):
        fn = opt(fn)
    return fn


def _selection(*, from_=None, to=None, cc=None, subject=None, text=None, since=None,
               before=None, seen=None, flagged=False, larger=None, smaller=None,
               header_filters=(), has_attachments=False, list_unsub=False) -> dict:
    """Split the selection options into a server-side criteria dict and a client-side
    predicate. `keep is None` means the server alone decides the result."""
    parsed_headers: list[tuple[str, str]] = []
    for hf in header_filters:
        if ":" in hf:
            k, _, v = hf.partition(":")
            parsed_headers.append((k.strip(), v.strip()))

    def _server(v):  # do NOT hand non-ASCII values to the server (Gluon unreliable) → client-side
        return v if v and not search_mod.is_non_ascii(v) else None

    return {
        "criteria": search_mod.build_criteria(
            from_=_server(from_), to=_server(to), cc=_server(cc), subject=_server(subject),
            text=None, since=since, before=before, seen=seen, flagged=flagged,
            larger=larger, smaller=smaller,
        ),
        "keep": search_mod.predicate(
            text=text, from_=from_, to=to, cc=cc, subject=subject,
            headers=parsed_headers or None, has_attachments=has_attachments,
            list_unsubscribe=list_unsub,
        ),
        # body text and attachments cannot be judged from headers → the scan must fetch fully
        "scan_needs_body": bool(text) or has_attachments,
        "with_body": bool(text),
        "include_headers": bool(parsed_headers),
    }


def _merge_stats(agg: dict, stats: dict) -> None:
    agg["candidates"] += stats["candidates"]
    agg["scanned"] += stats["scanned"]
    if stats["truncated"]:
        agg["truncated"] = True
        agg["reason"] = stats.get("reason", "")


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
            recs, _ = c.search(
                crit, folder=folder, limit=offset + limit, with_body=False, with_attachments=False
            )
            return recs[offset:offset + limit]

    out_mod.out(for_accounts(accounts, fn))


@message_group.command("search")
@select_options
@click.option("--folder", default=None, help="Folder; without it: All Mail (everything).")
@click.option("--all-folders", "all_folders", is_flag=True,
              help="Iterate over all folders (dedup).")
@click.option("--with-body", is_flag=True)
@click.option("--with-attachments", is_flag=True)
@click.option("--ids-only", "ids_only", is_flag=True,
              help="Only account/folder/uid/message_id per hit (for follow-up ops).")
@click.option("--count-only", "count_only", is_flag=True,
              help="Count only — server-side, no message fetch; ignores --limit.")
@click.option("--limit", type=int, default=50,
              help="Maximum number of MATCHES (0 = all). Client-side filters keep reading "
                   "until this many hits are found or the scope is exhausted.")
@click.option("--max-fetch", "max_fetch", type=int, default=0,
              help="Stop the client-side scan after N fetched messages (0 = no budget). "
                   "An exhausted budget is reported as truncated/reason in the result.")
@click.pass_context
def search_cmd(ctx, folder, all_folders, with_body, with_attachments,
               ids_only, count_only, limit, max_fetch, **selection) -> None:
    """Bulk search, newest first. Default scope: All Mail. Body/text & non-ASCII client-side."""
    from proton_mail_bridge.core.imap import dedup_by_message_id

    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")
    sel = _selection(**selection)
    cap = _cap(limit)
    budget = _cap(max_fetch)

    if count_only:
        # ponytail: counts server-side only (UID SEARCH); a client-side filter would only be
        # honest after a full scan → run the search itself instead of counting a window
        if ids_only:
            out_mod.out_err("usage", "Not combinable", "--count-only excludes --ids-only")
        if sel["keep"] is not None or all_folders:
            out_mod.out_err(
                "usage", "--count-only counts server-side",
                "not combinable with --text/--header/--has-attachments/--list-unsubscribe/"
                "--all-folders or non-ASCII values — those are decided client-side, and "
                "counting them means fetching them: run the search without --count-only",
            )

        def fn_count(account):
            with ImapClient.connect(cfg.endpoint, account) as c:
                f = c.resolve_folder(folder, "all")
                return {"folder": f, "count": c.count(sel["criteria"], f)}

        out_mod.out(for_accounts(accounts, fn_count))
        return

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            folders = c.list_folders() if all_folders else [c.resolve_folder(folder, "all")]
            recs: list[dict] = []
            agg: dict = {"candidates": 0, "scanned": 0, "truncated": False}
            for f in folders:
                found, stats = c.search(
                    sel["criteria"], folder=f, limit=cap,
                    with_body=with_body or sel["with_body"], with_attachments=with_attachments,
                    include_headers=sel["include_headers"], keep=sel["keep"],
                    scan_needs_body=sel["scan_needs_body"], max_fetch=budget,
                )
                recs.extend(found)
                _merge_stats(agg, stats)
            recs = dedup_by_message_id(recs)
            if cap and len(recs) > cap:
                recs = recs[:cap]
                agg.update(truncated=True, reason="limit")
            if ids_only:
                recs = [{"account": r["account"], "folder": r["folder"], "uid": r["uid"],
                         "message_id": r["message_id"]} for r in recs]
            return recs, {"search": {**agg, "limit": cap, "folders": len(folders)}}

    out_mod.out(for_accounts(accounts, fn))


@message_group.command("senders")
@click.option("--folder", default=None, help="Folder; without it: All Mail (everything).")
@click.option("--since", default=None)
@click.option("--before", default=None)
@click.option("--seen/--unseen", default=None)
@click.option("--min-count", "min_count", type=int, default=1,
              help="Only senders with at least N messages.")
@click.option("--limit", type=int, default=100, help="Top N senders by count (0 = all).")
@click.option("--max-fetch", "max_fetch", type=int, default=0,
              help="Stop after N scanned messages (0 = no budget); reported as truncated.")
@click.pass_context
def senders_cmd(ctx, folder, since, before, seen, min_count, limit, max_fetch) -> None:
    """Who sends the most: count, last date and last subject per From address.

    Headers only — no body fetch. `list_unsubscribe` marks senders that offer an unsubscribe
    header; that is a bulk-sender hint, not a reason to delete.
    """
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")
    crit = search_mod.build_criteria(since=since, before=before, seen=seen)
    cap = _cap(limit)

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            f = c.resolve_folder(folder, "all")
            rows, stats = c.sender_stats(crit, folder=f, max_fetch=_cap(max_fetch))
            rows.sort(key=lambda r: (-r["count"], r["from"]))
            kept = [r for r in rows if r["count"] >= min_count]
            shown = kept[:cap] if cap else kept
            return shown, {"senders": {**stats, "folder": f, "senders_total": len(kept),
                                       "limit": cap}}

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
                c.ensure_writable(folder, "message read --mark-read")
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


def _plan(client, action: str, account, uids: list[str], folder: str, risk: str,
          **fields) -> None:
    """Dry-run payload for a UID operation: one entry per message that would be touched,
    plus the UIDs the folder does not hold — enough to judge the selection before it runs."""
    messages = client.preview(uids, folder)
    known = {m["uid"] for m in messages}
    out_mod.out_plan(action, {
        "account": account.email,
        "folder": folder,
        "risk": risk,
        "count": len(messages),
        "missing_uids": [u for u in uids if u not in known],
        **fields,
        "messages": messages,
    })


@message_group.command("move")
@click.option("--uid", required=True)
@click.option("--to", "dest", required=True)
@click.option("--folder", default="INBOX")
@click.option("--yes", "assume_yes", is_flag=True)
@out_mod.dry_run_option
@click.pass_context
def move_cmd(ctx, uid, dest, folder, assume_yes, dry_run) -> None:
    """Move message(s) into a folder (🟡)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    risk = guard.escalate(guard.CONFIRM, count=len(uids))
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.ensure_writable(folder, "message move")
        c.ensure_writable(dest, "message move --to")
        if dry_run:
            _plan(c, "message move", account, uids, folder, risk, to=dest)
            return
        guard.enforce(f"message move {uids} → {dest}", risk, assume_yes=assume_yes)
        c.move(uids, folder=folder, dest=dest)
    out_mod.out_ok(f"{len(uids)} moved → {dest}")


@message_group.command("copy")
@click.option("--uid", required=True)
@click.option("--to", "dest", required=True)
@click.option("--folder", default="INBOX")
@out_mod.dry_run_option
@click.pass_context
def copy_cmd(ctx, uid, dest, folder, dry_run) -> None:
    """Copy message(s) into a folder (🟢)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.ensure_writable(dest, "message copy --to")
        if dry_run:
            _plan(c, "message copy", account, uids, folder, guard.FREE, to=dest)
            return
        c.copy(uids, folder=folder, dest=dest)
    out_mod.out_ok(f"{len(uids)} copied → {dest}")


@message_group.command("flag")
@click.option("--uid", required=True)
@click.option("--add", multiple=True)
@click.option("--remove", multiple=True)
@click.option("--folder", default="INBOX")
@click.option("--yes", "assume_yes", is_flag=True)
@out_mod.dry_run_option
@click.pass_context
def flag_cmd(ctx, uid, add, remove, folder, assume_yes, dry_run) -> None:
    """Set/remove flags (🟢 add only; 🟡 with remove)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    risk = guard.escalate(guard.CONFIRM if remove else guard.FREE, count=len(uids))
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.ensure_writable(folder, "message flag")
        if dry_run:
            _plan(c, "message flag", account, uids, folder, risk,
                  add=list(add), remove=list(remove))
            return
        guard.enforce(f"message flag {uids}", risk, assume_yes=assume_yes)
        c.set_flags(uids, folder=folder, add=list(add), remove=list(remove))
    out_mod.out_ok(f"Flags updated ({len(uids)}).")


@message_group.command("mark")
@click.option("--uid", required=True)
@click.option("--read/--unread", "read", required=True)
@click.option("--folder", default="INBOX")
@out_mod.dry_run_option
@click.pass_context
def mark_cmd(ctx, uid, read, folder, dry_run) -> None:
    """Mark as read/unread (🟢)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.ensure_writable(folder, "message mark")
        add_flags = ["\\Seen"] if read else []
        remove_flags = [] if read else ["\\Seen"]
        if dry_run:
            _plan(c, "message mark", account, uids, folder, guard.FREE,
                  add=add_flags, remove=remove_flags)
            return
        c.set_flags(uids, folder=folder, add=add_flags, remove=remove_flags)
    out_mod.out_ok(f"{len(uids)} marked ({'read' if read else 'unread'}).")


@message_group.command("delete")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--expunge", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@out_mod.dry_run_option
@click.pass_context
def delete_cmd(ctx, uid, folder, expunge, assume_yes, dry_run) -> None:
    """Delete: without --expunge → Trash 🟡; --expunge / from Trash / bulk ≥ 20 → permanent 🔴."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    uids = _uids(uid)
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.ensure_writable(folder, "message delete")
        trash = c.special_folders().get("trash", "Trash")
        permanent = expunge or folder == trash
        risk = guard.CRITICAL if permanent else guard.escalate(guard.CONFIRM, count=len(uids))
        if dry_run:
            _plan(c, "message delete", account, uids, folder, risk,
                  permanent=permanent, to=None if permanent else trash)
            return
        guard.enforce(f"message delete {uids} permanent={permanent}", risk,
                      assume_yes=assume_yes, token="delete")
        if permanent:
            c.delete(uids, folder=folder)
            action = "permanently deleted"
        else:
            c.move(uids, folder=folder, dest=trash)
            action = f"moved to {trash}"
    out_mod.out_ok(f"{len(uids)} {action}.")


def _bulk_select(client, sel: dict, folder: str | None, all_folders: bool,
                 cap: int | None, budget: int | None, skip: set[str]) -> tuple[list[dict], dict]:
    """Run the selection folder by folder. Returns one group per folder that has hits.

    All Mail is skipped: it is a duplicate view over every other folder and read-only, so
    every hit there is already covered by the folder the mail really lives in.
    """
    folders = client.list_folders() if all_folders else [folder or "INBOX"]
    groups: list[dict] = []
    agg: dict = {"candidates": 0, "scanned": 0, "truncated": False,
                 "skipped_folders": []}
    for f in folders:
        if f in skip or client.is_all_mail(f):
            agg["skipped_folders"].append(f)
            continue
        recs, stats = client.search(
            sel["criteria"], folder=f, limit=cap, with_body=sel["with_body"],
            with_attachments=False, include_headers=sel["include_headers"],
            keep=sel["keep"], scan_needs_body=sel["scan_needs_body"], max_fetch=budget,
        )
        _merge_stats(agg, stats)
        if recs:
            groups.append({
                "folder": f,
                "count": len(recs),
                "uids": [r["uid"] for r in recs],
                "messages": [{"uid": r["uid"], "folder": f, "date": r["date"],
                              "from": r["from"], "subject": r["subject"]} for r in recs],
            })
    return groups, agg


bulk_scope_opts = [
    click.option("--folder", default=None, help="Single folder (default INBOX)."),
    click.option("--all-folders", "all_folders", is_flag=True,
                 help="Every folder except All Mail (which is a read-only duplicate view)."),
    click.option("--limit", type=int, default=0,
                 help="Cap the selection PER FOLDER (0 = every match)."),
    click.option("--max-fetch", "max_fetch", type=int, default=0,
                 help="Stop the client-side scan after N fetched messages per folder "
                      "(0 = no budget); an exhausted budget is reported as truncated."),
    click.option("--yes", "assume_yes", is_flag=True),
]


def bulk_options(fn):
    for opt in reversed(bulk_scope_opts):
        fn = opt(fn)
    return select_options(fn)


@message_group.command("bulk-move")
@bulk_options
@click.option("--dest", required=True,
              help="Destination folder (--to keeps its search meaning: recipient).")
@out_mod.dry_run_option
@click.pass_context
def bulk_move_cmd(ctx, dest, folder, all_folders, limit, max_fetch, assume_yes, dry_run,
                  **selection) -> None:
    """Move every message matching the selection, folder by folder (🟡/🔴 from 20 on)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    sel = _selection(**selection)
    with ImapClient.connect(cfg.endpoint, account) as c:
        c.ensure_writable(dest, "message bulk-move --dest")
        if folder:
            c.ensure_writable(folder, "message bulk-move")
        groups, stats = _bulk_select(c, sel, folder, all_folders, _cap(limit),
                                     _cap(max_fetch), skip={dest})
        total = sum(g["count"] for g in groups)
        risk = guard.escalate(guard.CONFIRM, count=total)
        if dry_run:
            out_mod.out_plan("message bulk-move", {
                "account": account.email, "risk": risk, "dest": dest, "total": total,
                "folders": groups, "search": stats,
            })
            return
        if not total:
            out_mod.out({"ok": True, "action": "message bulk-move", "account": account.email,
                         "total": 0, "folders": [], "search": stats})
            return
        guard.enforce(f"message bulk-move {total} messages → {dest}", risk,
                      assume_yes=assume_yes)
        done = []
        for g in groups:
            c.move(g["uids"], folder=g["folder"], dest=dest)
            done.append({"folder": g["folder"], "count": g["count"], "uids": g["uids"]})
    out_mod.out({"ok": True, "action": "message bulk-move", "account": account.email,
                 "dest": dest, "total": total, "folders": done, "search": stats})


@message_group.command("bulk-delete")
@bulk_options
@click.option("--expunge", is_flag=True, help="Delete permanently instead of moving to Trash.")
@out_mod.dry_run_option
@click.pass_context
def bulk_delete_cmd(ctx, folder, all_folders, limit, max_fetch, assume_yes, expunge,
                    dry_run, **selection) -> None:
    """Delete every message matching the selection, folder by folder (🟡; 🔴 permanent/≥ 20)."""
    from proton_mail_bridge.core import guard

    cfg, account = _resolve_one(ctx)
    sel = _selection(**selection)
    with ImapClient.connect(cfg.endpoint, account) as c:
        if folder:
            c.ensure_writable(folder, "message bulk-delete")
        trash = c.special_folders().get("trash", "Trash")
        # soft delete = move to Trash, so Trash itself has nothing to contribute
        groups, stats = _bulk_select(c, sel, folder, all_folders, _cap(limit),
                                     _cap(max_fetch), skip=set() if expunge else {trash})
        total = sum(g["count"] for g in groups)
        risk = guard.CRITICAL if expunge else guard.escalate(guard.CONFIRM, count=total)
        if dry_run:
            out_mod.out_plan("message bulk-delete", {
                "account": account.email, "risk": risk, "permanent": expunge,
                "to": None if expunge else trash, "total": total,
                "folders": groups, "search": stats,
            })
            return
        if not total:
            out_mod.out({"ok": True, "action": "message bulk-delete", "account": account.email,
                         "total": 0, "folders": [], "search": stats})
            return
        guard.enforce(f"message bulk-delete {total} messages permanent={expunge}", risk,
                      assume_yes=assume_yes, token="delete")
        done = []
        for g in groups:
            if expunge:
                c.delete(g["uids"], folder=g["folder"])
            else:
                c.move(g["uids"], folder=g["folder"], dest=trash)
            done.append({"folder": g["folder"], "count": g["count"], "uids": g["uids"]})
    out_mod.out({"ok": True, "action": "message bulk-delete", "account": account.email,
                 "permanent": expunge, "to": None if expunge else trash, "total": total,
                 "folders": done, "search": stats})


def register(root: click.Group) -> None:
    root.add_command(message_group)
