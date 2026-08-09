from __future__ import annotations

import click

from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.identity import resolve_identity
from proton_mail_bridge.core.smtp import SmtpSession
from proton_mail_bridge.utils import mime
from proton_mail_bridge.utils import output as out_mod


@click.group("compose")
def compose_group() -> None:
    """Compose and send mail."""


def _csv(value: str | None) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()] if value else []


def _fetch_original(client, uid: str, folder: str, account_email: str) -> dict:
    """Original message for reply/forward. Names the mailbox we looked in when the UID is
    missing — with `--identity` the account may not be the one the caller had in mind."""
    found = client.fetch([uid], folder=folder, fmt="text", include_headers=True)
    if not found:
        out_mod.out_err(
            "not_found", "Message not found", f"uid={uid} in {folder} of {account_email}"
        )
    return found[0]


def _body(body: str | None, body_file: str | None) -> str:
    if body_file:
        from pathlib import Path

        return Path(body_file).read_text(encoding="utf-8")
    return body or ""


@compose_group.command("send")
@click.option("--to", required=True)
@click.option("--cc", default=None)
@click.option("--bcc", default=None)
@click.option("--subject", required=True)
@click.option("--body", default=None)
@click.option("--body-file", default=None)
@click.option("--html-file", default=None)
@click.option("--attach", multiple=True, type=click.Path(exists=True))
@click.option("--from", "from_", default=None)
@click.option("--identity", "identity", default=None,
              help="Sender identity: address or label (see `account identity`).")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def send_cmd(
    ctx, to, cc, bcc, subject, body, body_file, html_file, attach, from_, identity,
    dry_run, assume_yes
) -> None:
    """Send mail (🟡). Verifies the send via the returned Message-ID."""
    from proton_mail_bridge.core import guard

    cfg = cfgmod.resolve_config()
    account, ident = resolve_identity(cfg, identity, from_ or ctx.obj.get("account"))
    html = None
    if html_file:
        from pathlib import Path

        html = Path(html_file).read_text(encoding="utf-8")
    msg = mime.build_message(
        sender=ident.formatted(), to=_csv(to), cc=_csv(cc), bcc=_csv(bcc), subject=subject,
        body_text=_body(body, body_file), body_html=html, attachments=list(attach),
    )
    if dry_run:
        out_mod.out({"dry_run": True, "from": ident.email, "account": account.email,
                     "to": _csv(to), "subject": subject, "attachments": [a for a in attach]})
        return
    guard.enforce(f"compose send → {to}", guard.CONFIRM, assume_yes=assume_yes)
    with SmtpSession.connect(cfg.endpoint, account) as s:
        message_id = s.send(msg)
    out_mod.out({"ok": True, "message_id": message_id, "from": ident.email,
                 "account": account.email, "to": _csv(to)})


@compose_group.command("reply")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--all", "reply_all", is_flag=True)
@click.option("--body", default=None)
@click.option("--body-file", default=None)
@click.option("--attach", multiple=True, type=click.Path(exists=True))
@click.option("--identity", "identity", default=None,
              help="Sender identity; defaults to the address the mail was sent to.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def reply_cmd(
    ctx, uid, folder, reply_all, body, body_file, attach, identity, dry_run, assume_yes
) -> None:
    """Reply to a message (🟡, sets In-Reply-To/References)."""
    from proton_mail_bridge.core import guard
    from proton_mail_bridge.core.identity import own_addresses, pick_reply_identity
    from proton_mail_bridge.core.imap import ImapClient

    cfg = cfgmod.resolve_config()
    account, chosen = resolve_identity(cfg, identity, ctx.obj.get("account"))
    with ImapClient.connect(cfg.endpoint, account) as c:
        original = _fetch_original(c, uid, folder, account.email)
    # explicit --identity wins; otherwise answer from the address the mail was sent to
    ident = chosen if identity else pick_reply_identity(account, original)
    import re as _re
    base_subject = _re.sub(r"^(re:\s*)+", "", original["subject"], flags=_re.IGNORECASE)
    recipients = [original["from"]]
    cc_list: list[str] = []
    if reply_all:
        # drop every own address of this account and duplicates
        mine = own_addresses(account)
        recipients += [a for a in original["to"]
                       if a.lower() not in mine and a != original["from"]]
        cc_list = [a for a in original["cc"] if a.lower() not in mine]
    msg = mime.build_message(
        sender=ident.formatted(), to=recipients, cc=cc_list or None, bcc=None,
        subject="Re: " + base_subject, body_text=_body(body, body_file),
        body_html=None, attachments=list(attach),
        in_reply_to=original["message_id"], references=[original["message_id"]],
    )
    if dry_run:
        out_mod.out({"dry_run": True, "from": ident.email, "account": account.email,
                     "to": recipients, "cc": cc_list, "subject": msg["Subject"]})
        return
    guard.enforce(f"compose reply uid={uid} ({account.email})", guard.CONFIRM,
                  assume_yes=assume_yes)
    with SmtpSession.connect(cfg.endpoint, account) as s:
        message_id = s.send(msg)
    out_mod.out({"ok": True, "message_id": message_id, "from": ident.email,
                 "account": account.email})


@compose_group.command("forward")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--to", required=True)
@click.option("--body", default=None)
@click.option("--identity", "identity", default=None,
              help="Sender identity; defaults to the address the mail was sent to.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def forward_cmd(ctx, uid, folder, to, body, identity, dry_run, assume_yes) -> None:
    """Forward a message (🟡)."""
    from proton_mail_bridge.core import guard
    from proton_mail_bridge.core.identity import pick_reply_identity
    from proton_mail_bridge.core.imap import ImapClient

    cfg = cfgmod.resolve_config()
    account, chosen = resolve_identity(cfg, identity, ctx.obj.get("account"))
    with ImapClient.connect(cfg.endpoint, account) as c:
        original = _fetch_original(c, uid, folder, account.email)
        atts: list[str | tuple[str, bytes, str | None]] = [
            (a.filename, a.payload, a.content_type) for a in c.attachments(uid, folder=folder)
        ]
    ident = chosen if identity else pick_reply_identity(account, original)
    fwd_body = (
        (body or "")
        + "\n\n---------- Forwarded message ----------\n"
        + (original.get("body_text") or "")
    )
    msg = mime.build_message(
        sender=ident.formatted(), to=_csv(to), cc=None, bcc=None,
        subject="Fwd: " + original["subject"], body_text=fwd_body, body_html=None, attachments=atts,
    )
    if dry_run:
        out_mod.out({"dry_run": True, "from": ident.email, "account": account.email,
                     "to": _csv(to), "subject": msg["Subject"]})
        return
    guard.enforce(f"compose forward uid={uid} → {to} ({account.email})", guard.CONFIRM,
                  assume_yes=assume_yes)
    with SmtpSession.connect(cfg.endpoint, account) as s:
        message_id = s.send(msg)
    out_mod.out({"ok": True, "message_id": message_id, "from": ident.email,
                 "account": account.email})


@compose_group.command("draft")
@click.option("--to", required=True)
@click.option("--subject", required=True)
@click.option("--body", default=None)
@click.option("--body-file", default=None)
@click.option("--attach", multiple=True, type=click.Path(exists=True))
@click.option("--folder", default=None)
@click.option("--identity", "identity", default=None,
              help="Sender identity: address or label (see `account identity`).")
@click.pass_context
def draft_cmd(ctx, to, subject, body, body_file, attach, folder, identity) -> None:
    """Store a draft in Drafts via IMAP APPEND (🟢)."""
    from proton_mail_bridge.core.imap import ImapClient

    cfg = cfgmod.resolve_config()
    account, ident = resolve_identity(cfg, identity, ctx.obj.get("account"))
    msg = mime.build_message(
        sender=ident.formatted(), to=_csv(to), cc=None, bcc=None, subject=subject,
        body_text=_body(body, body_file), body_html=None, attachments=list(attach),
    )
    with ImapClient.connect(cfg.endpoint, account) as c:
        target = folder or c.special_folders().get("drafts", "Drafts")
        c.append(msg.as_bytes(), target, flags=["\\Draft"])
    out_mod.out_ok(f"Draft stored in {target}.")


def register(root: click.Group) -> None:
    root.add_command(compose_group)
