from __future__ import annotations

from pathlib import Path

import click

from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import resolve_accounts
from proton_mail_bridge.core.imap import ImapClient, attachment_meta
from proton_mail_bridge.utils import output as out_mod


@click.group("attachment")
def attachment_group() -> None:
    """List, download, and extract attachments."""


def _uids(value: str) -> list[str]:
    return [u.strip() for u in value.split(",") if u.strip()]


def _resolve_one(ctx):
    cfg = cfgmod.resolve_config()
    return cfg, resolve_accounts(cfg, ctx.obj.get("account"), mode="message_op")[0]


@attachment_group.command("list")
@click.option("--uid", required=True)
@click.option("--folder", default="INBOX")
@click.pass_context
def list_cmd(ctx, uid, folder) -> None:
    """List attachment metadata of the given UID(s)."""
    from proton_mail_bridge.core.imap import for_accounts

    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="message_op")

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            result = []
            for u in _uids(uid):
                result.extend(attachment_meta(a) for a in c.attachments(u, folder))
            return result

    out_mod.out(for_accounts(accounts, fn))


def _selected(client, uids, folder, name, index, download_all, out_dir):
    """(uid, attachment, target path) for every attachment the selection covers.
    Shared by the real run and the dry run so both can never disagree on the targets."""
    for u in uids:
        for i, att in enumerate(client.attachments(u, folder)):
            if not download_all and name and att.filename != name:
                continue
            if not download_all and index is not None and i != index:
                continue
            safe_name = Path(att.filename or "").name
            if not safe_name or safe_name in (".", ".."):
                safe_name = f"attachment_{i}"
            # prefix with the UID to avoid name collisions across multiple UIDs
            yield u, att, out_dir / f"{u}_{safe_name}"


@attachment_group.command("download")
@click.option("--uid", required=True)
@click.option("--name", default=None)
@click.option("--index", type=int, default=None)
@click.option("--all", "download_all", is_flag=True)
@click.option("--dir", "directory", required=True, type=click.Path())
@click.option("--folder", default="INBOX")
@out_mod.dry_run_option
@click.pass_context
def download_cmd(ctx, uid, name, index, download_all, directory, folder, dry_run) -> None:
    """Save attachments to disk (bulk via --uid 1,2,3 and/or --all)."""
    cfg, account = _resolve_one(ctx)
    out_dir = Path(directory)
    with ImapClient.connect(cfg.endpoint, account) as c:
        if dry_run:
            # no mkdir here either — a dry run must not leave an empty directory behind
            files = [
                {"uid": u, "filename": att.filename, "size": att.size,
                 "target": str(target), "exists": target.exists()}
                for u, att, target in _selected(c, _uids(uid), folder, name, index,
                                                download_all, out_dir)
            ]
            out_mod.out_plan("attachment download", {
                "account": account.email, "folder": folder, "dir": str(out_dir),
                "count": len(files), "overwrites": [f["target"] for f in files if f["exists"]],
                "files": files,
            })
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for _u, att, target in _selected(c, _uids(uid), folder, name, index,
                                         download_all, out_dir):
            target.write_bytes(att.payload)
            saved.append(str(target))
    out_mod.out({"ok": True, "saved": saved, "count": len(saved)})


@attachment_group.command("extract")
@click.option("--uid", required=True)
@click.option("--name", required=True)
@click.option("--folder", default="INBOX")
@click.pass_context
def extract_cmd(ctx, uid, name, folder) -> None:
    """Write a single attachment to stdout (for piping)."""
    cfg, account = _resolve_one(ctx)
    with ImapClient.connect(cfg.endpoint, account) as c:
        for att in c.attachments(uid, folder):
            if att.filename == name:
                click.get_binary_stream("stdout").write(att.payload)
                return
    out_mod.out_err("not_found", "Attachment not found", name)


def register(root: click.Group) -> None:
    root.add_command(attachment_group)
