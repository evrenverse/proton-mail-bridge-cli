from __future__ import annotations

import datetime as _dt

import click

from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import resolve_accounts
from proton_mail_bridge.core.imap import ImapClient, dedup_by_message_id, for_accounts
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
    click.option("--attachment-name", "attachment_name", default=None,
                 help="Substring of an attachment filename, case-insensitive. --text only "
                      "reads bodies, so this is the way to find a document that was "
                      "forwarded as a bare attachment (filtered client-side)."),
    click.option("--attachment-text", "attachment_text", default=None,
                 help="Substring of the text INSIDE a PDF attachment, case-insensitive. "
                      "Fetches and parses every PDF in scope, so narrow it with "
                      "--since/--folder. Scans have no text layer — no OCR here."),
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
               header_filters=(), has_attachments=False, attachment_name=None,
               attachment_text=None, list_unsub=False) -> dict:
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
            attachment_name=attachment_name, attachment_text=attachment_text,
            list_unsubscribe=list_unsub,
        ),
        # body text and attachments cannot be judged from headers → the scan must fetch fully
        "scan_needs_body": bool(text) or has_attachments or bool(attachment_name)
                           or bool(attachment_text),
        "with_body": bool(text),
        # filenames only exist on the record when the fetch carries attachment metadata
        "with_attachments": bool(attachment_name),
        "with_attachment_text": bool(attachment_text),
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
              help="Iterate over every folder except All Mail (a read-only duplicate view), "
                   "deduplicated by Message-ID — the folder-wise view write ops need.")
@click.option("--with-body", is_flag=True)
@click.option("--with-attachments", is_flag=True)
@click.option("--ids-only", "ids_only", is_flag=True,
              help="Only account/folder/uid/message_id per hit (for follow-up ops).")
@click.option("--count-only", "count_only", is_flag=True,
              help="Exact count; ignores --limit. Server-side criteria count without a "
                   "fetch; a client-side one is scanned and reports scanned/truncated.")
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
        if ids_only:
            out_mod.out_err("usage", "Not combinable", "--count-only excludes --ids-only")
        if all_folders:
            # counting folder by folder would count labelled mail several times; the default
            # scope (All Mail) already holds every message exactly once
            out_mod.out_err(
                "usage", "--count-only excludes --all-folders",
                "the same mail lives in INBOX + Labels/X + All Mail, so a per-folder count "
                "would count it repeatedly — count in All Mail (the default scope) instead",
            )

        def fn_count(account):
            with ImapClient.connect(cfg.endpoint, account) as c:
                f = c.resolve_folder(folder, "all")
                if sel["keep"] is None:  # server-side criteria only → UID SEARCH, no fetch
                    return {"folder": f, "count": c.count(sel["criteria"], f)}
                # a client-side criterion has to be scanned to be counted; materialize=False
                # skips completing the hits, because only their number is used
                hits, stats = c.search(
                    sel["criteria"], folder=f, limit=None,
                    with_body=sel["with_body"], with_attachments=sel["with_attachments"],
                    include_headers=sel["include_headers"], keep=sel["keep"],
                    scan_needs_body=sel["scan_needs_body"],
                    with_attachment_text=sel["with_attachment_text"],
                    materialize=False, max_fetch=budget,
                )
                return {"folder": f, "count": len(hits), **stats}

        out_mod.out(for_accounts(accounts, fn_count))
        return

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            folders = c.list_folders() if all_folders else [c.resolve_folder(folder, "all")]
            recs: list[dict] = []
            seen: set[str] = set()
            agg: dict = {"candidates": 0, "scanned": 0, "truncated": False,
                         "skipped_folders": []}
            for f in folders:
                # the point of --all-folders is the folder-wise view; All Mail would answer
                # first and hand back UIDs in the one folder nothing can be written to
                if all_folders and c.is_all_mail(f):
                    agg["skipped_folders"].append(f)
                    continue
                # ask each folder only for what is still missing: with 35 folders, asking
                # every one for the full limit fetches 35x more than the answer needs
                remaining = None if cap is None else cap - len(recs)
                if remaining is not None and remaining <= 0:
                    agg.update(truncated=True, reason="limit")  # folders left unscanned
                    break
                found, stats = c.search(
                    sel["criteria"], folder=f, limit=remaining,
                    with_body=with_body or sel["with_body"],
                    with_attachments=with_attachments or sel["with_attachments"],
                    include_headers=sel["include_headers"], keep=sel["keep"],
                    scan_needs_body=sel["scan_needs_body"],
                    with_attachment_text=sel["with_attachment_text"], max_fetch=budget,
                )
                _merge_stats(agg, stats)
                recs.extend(dedup_by_message_id(found, seen))
            if ids_only:
                recs = [{"account": r["account"], "folder": r["folder"], "uid": r["uid"],
                         "message_id": r["message_id"]} for r in recs]
            scanned_folders = len(folders) - len(agg["skipped_folders"])
            return recs, {"search": {**agg, "limit": cap, "folders": scanned_folders}}

    out_mod.out(for_accounts(accounts, fn))


@message_group.command("senders")
@click.option("--folder", default=None, help="Folder; without it: All Mail (everything).")
@click.option("--all-folders", "all_folders", is_flag=True,
              help="Scan every folder except All Mail and report per sender where the mails "
                   "sit (deduplicated by Message-ID) — the view a folder-wise cleanup needs.")
@click.option("--since", default=None)
@click.option("--before", default=None)
@click.option("--seen/--unseen", default=None)
@click.option("--min-count", "min_count", type=int, default=1,
              help="Only senders with at least N messages.")
@click.option("--limit", type=int, default=100, help="Top N senders by count (0 = all).")
@click.option("--max-fetch", "max_fetch", type=int, default=0,
              help="Stop after N scanned messages (0 = no budget); reported as truncated.")
@click.pass_context
def senders_cmd(ctx, folder, all_folders, since, before, seen, min_count, limit,
                max_fetch) -> None:
    """Who sends the most: count, last date and last subject per From address.

    Headers only — no body fetch. `folders` says where a sender's mails sit.
    `list_unsubscribe` marks senders that offer an unsubscribe header; that is a bulk-sender
    hint, not a reason to delete.
    """
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")
    crit = search_mod.build_criteria(since=since, before=before, seen=seen)
    cap = _cap(limit)

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            scope = c.list_folders() if all_folders else [c.resolve_folder(folder, "all")]
            rows, stats = c.sender_stats(crit, scope, max_fetch=_cap(max_fetch))
            rows.sort(key=lambda r: (-r["count"], r["from"]))
            kept = [r for r in rows if r["count"] >= min_count]
            shown = kept[:cap] if cap else kept
            return shown, {"senders": {**stats, "senders_total": len(kept), "limit": cap}}

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


@message_group.command("otp")
@click.option("--since", default="10m",
              help="How far back to look: 10m, 2h, 1d (a bare number means minutes). A "
                   "duration, not the ISO date the other commands take -- a code from "
                   "yesterday is not a code.")
@click.option("--from", "from_", default=None,
              help="Sender filter, e.g. the shop's domain. The one option that turns an "
                   "ambiguous window into an unambiguous one.")
@click.option("--folder", default=None,
              help="Single folder. Without it: INBOX and Spam, and All Mail as a fallback "
                   "when those two turn up no code -- a mail filter can move a "
                   "verification mail out of both.")
@click.pass_context
def otp_cmd(ctx, since, from_, folder) -> None:
    """The newest one-time verification code from a freshly arrived message.

    Prints the code and nothing else on stdout, so it can be piped straight into a form.
    Every message that also carried a candidate is listed in `also_found` WITHOUT its
    code -- read `ambiguous` before using the result, the way `search.truncated` is read.
    """
    from proton_mail_bridge.utils import otp as otp_mod

    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")
    try:
        window = otp_mod.parse_window(since)
    except ValueError as exc:
        out_mod.out_err("usage", "Invalid --since", str(exc), exit_code=2)
        return

    now = _dt.datetime.now(_dt.UTC)
    cutoff = now - window
    # IMAP SINCE compares dates in the server's timezone, not ours. A day of slack costs
    # one header scan and removes the edge where a message from minutes ago falls out of
    # the server-side window; the exact cut happens client-side below.
    crit = search_mod.build_criteria(
        from_=None if search_mod.is_non_ascii(from_) else from_,
        since=(cutoff.date() - _dt.timedelta(days=1)).isoformat(),
    )

    def keep(rec: dict) -> bool:
        when = otp_mod.parse_date(rec.get("date"))
        if when is None or when < cutoff:
            return False
        # --from is checked here as well as server-side. It is the option that decides
        # whose code ends up in a form, and IMAP FROM matching is not worth trusting on
        # its own -- the server-side criterion above only keeps the scan small.
        return not from_ or from_.lower() in str(rec.get("from", "")).lower()

    def scan(client, folders: list[str]) -> tuple[list[dict], int]:
        recs: list[dict] = []
        scanned = 0
        for f in folders:
            # headers-only scan (scan_needs_body=False) decides freshness; only the
            # few survivors are fetched with a body
            found, stats = client.search(crit, folder=f, limit=None, with_body=True,
                                         with_attachments=False, keep=keep,
                                         scan_needs_body=False)
            scanned += stats["scanned"]
            recs.extend(found)
        return recs, scanned

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            if folder:  # an explicit folder is an instruction, not a starting point
                recs, scanned = scan(c, [folder])
                return recs, {"scanned": scanned, "folders": [folder]}
            near = _otp_folders(c)
            recs, scanned = scan(c, near)
            if _has_usable_code(recs):
                return recs, {"scanned": scanned, "folders": near}
            # A mail filter can move verification mail out of INBOX and Spam entirely.
            # Measured against a real mailbox: a Proton filter had put an Indeed login
            # code in `Folders/Indeed`, and the near scan reported nothing at all. All
            # Mail is the one scope that cannot miss a folder, and it is only paid for on
            # the path that was about to fail anyway. Deduplicating keeps the real folder
            # of anything the near scan already found -- All Mail cannot be written to.
            wide = [c.resolve_folder(None, "all")]
            far, far_scanned = scan(c, wide)
            return (dedup_by_message_id(recs + far),
                    {"scanned": scanned + far_scanned, "folders": near + wide})

    results = for_accounts(accounts, fn)
    _emit_otp(results, since=since, now=now)


def _has_usable_code(records: list[dict]) -> bool:
    """Whether any of these messages yields exactly one code -- the only kind that can be
    used. A message offering several is not a reason to stop looking elsewhere."""
    from proton_mail_bridge.utils import otp as otp_mod

    return any(
        len(otp_mod.extract(r.get("subject"), r.get("body_text"), r.get("body_html"))) == 1
        for r in records
    )


def _otp_folders(client) -> list[str]:
    """INBOX plus the Spam folder under whatever name this account gives it."""
    junk = client.special_folders().get("junk")
    return ["INBOX"] + ([junk] if junk and junk != "INBOX" else [])


def _emit_otp(results: list[dict], *, since: str, now: _dt.datetime) -> None:
    """Pick the newest usable message and print its code -- or fail without quoting one.

    A message that yields several candidates is never used: there is nothing in it that
    says which one the form wants. Across messages the newest wins, and everything it
    displaced is reported.
    """
    from proton_mail_bridge.utils import otp as otp_mod

    scanned = sum(r.get("scanned", 0) for r in results if r.get("ok"))
    folders = sorted({f for r in results if r.get("ok") for f in r.get("folders", [])})
    failed = [r["account"] for r in results if not r.get("ok")]

    # (arrival, record, code) -- the timestamp is carried along because the selection is
    # by time, and parsing it twice would be two chances to disagree with itself
    usable: list[tuple[_dt.datetime, dict, str]] = []
    unusable: list[dict] = []
    for rec in (rec for r in results if r.get("ok") for rec in r["items"]):
        codes = otp_mod.extract(rec.get("subject"), rec.get("body_text"),
                                rec.get("body_html"))
        when = otp_mod.parse_date(rec.get("date"))
        if when is None:  # the freshness filter already rejected these
            continue
        if len(codes) == 1:
            usable.append((when, rec, codes[0]))
        elif codes:
            unusable.append(rec)

    usable.sort(key=lambda found: found[0], reverse=True)
    scope = f"{scanned} messages in {', '.join(folders) or 'no folder'}"
    if failed:
        scope += f" ({len(failed)} account(s) unreachable: {', '.join(failed)})"

    if not usable:
        if unusable:
            out_mod.out_err(
                "otp_ambiguous", f"No usable code in the last {since}",
                f"{len(unusable)} message(s) carried several candidates each, and nothing "
                f"in them says which one belongs in the form. Narrow it with --from. "
                f"Scanned {scope}.",
            )
            return
        out_mod.out_err(
            "otp_not_found", f"No verification code in the last {since}",
            f"Scanned {scope}. Widen --since, drop --from, or name the folder the mail "
            f"landed in with --folder.",
        )
        return

    when, rec, code = usable[0]
    # every message that also produced something -- described, never quoted
    also = [
        {"account": other["account"], "folder": other["folder"], "uid": other["uid"],
         "from": other["from"], "date": other["date"],
         "shape": otp_mod.shape(other_code) if other_code else "several candidates"}
        for other, other_code in ([(r, c) for _, r, c in usable[1:]]
                                  + [(o, "") for o in unusable])
    ]
    age = int((now - when).total_seconds())
    payload = {
        "code": code,
        "account": rec["account"], "folder": rec["folder"], "uid": rec["uid"],
        "from": rec["from"], "subject": rec["subject"], "date": rec["date"],
        "age_seconds": age, "window": since, "scanned": scanned, "folders": folders,
        "ambiguous": bool(also), "also_found": also,
    }
    if not out_mod.is_json():
        # the bare code on stdout, so `pmb message otp | xclip` is the whole story;
        # context goes to stderr, which never carries the code itself
        click.echo(code)
        click.echo(f"  {rec['from']} · {age}s ago · {rec['folder']} · uid {rec['uid']}",
                   err=True)
        if also:
            click.echo(f"  ambiguous: {len(also)} other message(s) in this window carried "
                       f"a candidate — narrow with --from", err=True)
        return
    out_mod.out(payload)


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


def _write_log(path: str, action: str, account: str, messages: list[dict]) -> None:
    """One JSON line per message, appended. Written *before* the delete: a log that
    overstates is recoverable, a message that vanished without a trace is not."""
    import json
    import time
    from pathlib import Path

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    with target.open("a", encoding="utf-8") as fh:
        for m in messages:
            fh.write(json.dumps({"ts": stamp, "action": action, "account": account,
                                 "folder": m.get("folder"), "uid": m.get("uid"),
                                 "date": m.get("date"), "from": m.get("from"),
                                 "subject": m.get("subject")}, ensure_ascii=False) + "\n")


log_option = click.option(
    "--log", "log_path", type=click.Path(), default=None,
    help="Append one JSON line per deleted message (folder, uid, from, subject, date). "
         "Written before the delete — without it, the only record of a permanently deleted "
         "message is its absence.",
)


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
@log_option
@out_mod.dry_run_option
@click.pass_context
def delete_cmd(ctx, uid, folder, expunge, assume_yes, log_path, dry_run) -> None:
    """Delete → Trash 🟡 (🔴 from 20 on); --expunge / from Trash → permanent 🔴."""
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
                  permanent=permanent, to=None if permanent else trash, log=log_path)
            return
        guard.enforce(f"message delete {uids} permanent={permanent}", risk,
                      assume_yes=assume_yes, token="delete")
        if log_path:
            _write_log(log_path, "message delete", account.email, c.preview(uids, folder))
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
            with_attachments=sel["with_attachments"], include_headers=sel["include_headers"],
            keep=sel["keep"], scan_needs_body=sel["scan_needs_body"],
            with_attachment_text=sel["with_attachment_text"], max_fetch=budget,
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
@log_option
@out_mod.dry_run_option
@click.pass_context
def bulk_delete_cmd(ctx, folder, all_folders, limit, max_fetch, assume_yes, expunge,
                    log_path, dry_run, **selection) -> None:
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
                "to": None if expunge else trash, "total": total, "log": log_path,
                "folders": groups, "search": stats,
            })
            return
        if not total:
            out_mod.out({"ok": True, "action": "message bulk-delete", "account": account.email,
                         "total": 0, "folders": [], "search": stats})
            return
        guard.enforce(f"message bulk-delete {total} messages permanent={expunge}", risk,
                      assume_yes=assume_yes, token="delete")
        if log_path:
            _write_log(log_path, "message bulk-delete", account.email,
                       [m for g in groups for m in g["messages"]])
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
