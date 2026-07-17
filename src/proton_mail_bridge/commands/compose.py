from __future__ import annotations

import click

from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import resolve_accounts
from proton_mail_bridge.core.smtp import SmtpSession
from proton_mail_bridge.utils import mime
from proton_mail_bridge.utils import output as out_mod


@click.group("compose")
def compose_group() -> None:
    """Compose and send mail."""


def _csv(value: str | None) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()] if value else []


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
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def send_cmd(
    ctx, to, cc, bcc, subject, body, body_file, html_file, attach, from_, dry_run, assume_yes
) -> None:
    """Send mail (🟡). Verifies the send via the returned Message-ID."""
    from proton_mail_bridge.core import guard

    cfg = cfgmod.resolve_config()
    arg = from_ or ctx.obj.get("account")
    account = resolve_accounts(cfg, arg, mode="identity")[0]
    html = None
    if html_file:
        from pathlib import Path

        html = Path(html_file).read_text(encoding="utf-8")
    msg = mime.build_message(
        sender=account.email, to=_csv(to), cc=_csv(cc), bcc=_csv(bcc), subject=subject,
        body_text=_body(body, body_file), body_html=html, attachments=list(attach),
    )
    if dry_run:
        out_mod.out({"dry_run": True, "from": account.email, "to": _csv(to),
                     "subject": subject, "attachments": [a for a in attach]})
        return
    guard.enforce(f"compose send → {to}", guard.CONFIRM, assume_yes=assume_yes)
    with SmtpSession.connect(cfg.endpoint, account) as s:
        message_id = s.send(msg)
    out_mod.out({"ok": True, "message_id": message_id, "from": account.email, "to": _csv(to)})


@compose_group.command("reply")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--all", "reply_all", is_flag=True)
@click.option("--body", default=None)
@click.option("--body-file", default=None)
@click.option("--attach", multiple=True, type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def reply_cmd(ctx, uid, folder, reply_all, body, body_file, attach, dry_run, assume_yes) -> None:
    """Reply to a message (🟡, sets In-Reply-To/References)."""
    from proton_mail_bridge.core import guard
    from proton_mail_bridge.core.imap import ImapClient

    cfg = cfgmod.resolve_config()
    account = resolve_accounts(cfg, ctx.obj.get("account"), mode="identity")[0]
    with ImapClient.connect(cfg.endpoint, account) as c:
        original = c.fetch([uid], folder=folder, fmt="text", include_headers=True)[0]
    import re as _re
    base_subject = _re.sub(r"^(re:\s*)+", "", original["subject"], flags=_re.IGNORECASE)
    recipients = [original["from"]]
    cc_list: list[str] = []
    if reply_all:
        # drop own address and duplicates; original To → To, original Cc → Cc
        recipients += [a for a in original["to"]
                       if a != account.email and a != original["from"]]
        cc_list = [a for a in original["cc"] if a != account.email]
    msg = mime.build_message(
        sender=account.email, to=recipients, cc=cc_list or None, bcc=None,
        subject="Re: " + base_subject, body_text=_body(body, body_file),
        body_html=None, attachments=list(attach),
        in_reply_to=original["message_id"], references=[original["message_id"]],
    )
    if dry_run:
        out_mod.out({"dry_run": True, "to": recipients, "cc": cc_list, "subject": msg["Subject"]})
        return
    guard.enforce(f"compose reply uid={uid}", guard.CONFIRM, assume_yes=assume_yes)
    with SmtpSession.connect(cfg.endpoint, account) as s:
        message_id = s.send(msg)
    out_mod.out({"ok": True, "message_id": message_id})


@compose_group.command("forward")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.option("--to", required=True)
@click.option("--body", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def forward_cmd(ctx, uid, folder, to, body, dry_run, assume_yes) -> None:
    """Forward a message (🟡)."""
    from proton_mail_bridge.core import guard
    from proton_mail_bridge.core.imap import ImapClient

    cfg = cfgmod.resolve_config()
    account = resolve_accounts(cfg, ctx.obj.get("account"), mode="identity")[0]
    with ImapClient.connect(cfg.endpoint, account) as c:
        original = c.fetch([uid], folder=folder, fmt="text", include_headers=False)[0]
        atts: list[str | tuple[str, bytes, str | None]] = [
            (a.filename, a.payload, a.content_type) for a in c.attachments(uid, folder=folder)
        ]
    fwd_body = (
        (body or "")
        + "\n\n---------- Forwarded message ----------\n"
        + (original.get("body_text") or "")
    )
    msg = mime.build_message(
        sender=account.email, to=_csv(to), cc=None, bcc=None,
        subject="Fwd: " + original["subject"], body_text=fwd_body, body_html=None, attachments=atts,
    )
    if dry_run:
        out_mod.out({"dry_run": True, "to": _csv(to), "subject": msg["Subject"]})
        return
    guard.enforce(f"compose forward uid={uid} → {to}", guard.CONFIRM, assume_yes=assume_yes)
    with SmtpSession.connect(cfg.endpoint, account) as s:
        message_id = s.send(msg)
    out_mod.out({"ok": True, "message_id": message_id})


@compose_group.command("draft")
@click.option("--to", required=True)
@click.option("--subject", required=True)
@click.option("--body", default=None)
@click.option("--body-file", default=None)
@click.option("--attach", multiple=True, type=click.Path(exists=True))
@click.option("--folder", default=None)
@click.pass_context
def draft_cmd(ctx, to, subject, body, body_file, attach, folder) -> None:
    """Store a draft in Drafts via IMAP APPEND (🟢)."""
    from proton_mail_bridge.core.imap import ImapClient

    cfg = cfgmod.resolve_config()
    account = resolve_accounts(cfg, ctx.obj.get("account"), mode="identity")[0]
    msg = mime.build_message(
        sender=account.email, to=_csv(to), cc=None, bcc=None, subject=subject,
        body_text=_body(body, body_file), body_html=None, attachments=list(attach),
    )
    with ImapClient.connect(cfg.endpoint, account) as c:
        target = folder or c.special_folders().get("drafts", "Drafts")
        c.append(msg.as_bytes(), target, flags=["\\Draft"])
    out_mod.out_ok(f"Draft stored in {target}.")


def register(root: click.Group) -> None:
    root.add_command(compose_group)
