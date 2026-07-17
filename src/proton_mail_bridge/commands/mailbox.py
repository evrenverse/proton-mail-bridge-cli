from __future__ import annotations

import click

from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import resolve_accounts
from proton_mail_bridge.core.imap import ImapClient, for_accounts
from proton_mail_bridge.utils import output as out_mod


@click.group("mailbox")
def mailbox_group() -> None:
    """Folders/labels."""


@mailbox_group.command("list")
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List all folders/labels per account."""
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            out = []
            for name in c.list_folders():
                st = c.folder_status(name)
                out.append({
                    "name": name,
                    "total": st.get("MESSAGES", 0),
                    "unread": st.get("UNSEEN", 0),
                })
            return {"folders": out}

    out_mod.out(for_accounts(accounts, fn))


@mailbox_group.command("create")
@click.argument("name")
@click.pass_context
def create_cmd(ctx: click.Context, name: str) -> None:
    """Create a folder/label (🟢). Proton: folders are `Folders/<name>`, labels `Labels/<name>`."""
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="message_op")
    if len(accounts) != 1:
        out_mod.out_err("account", "create needs exactly one account",
                        "pass --account <email|alias>")
    with ImapClient.connect(cfg.endpoint, accounts[0]) as c:
        c.create_folder(name)
    out_mod.out_ok(f"Folder {name} created.")


@mailbox_group.command("info")
@click.argument("folder")
@click.pass_context
def info_cmd(ctx: click.Context, folder: str) -> None:
    """Status of a folder (counts, uidvalidity)."""
    cfg = cfgmod.resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            return c.folder_status(folder)

    out_mod.out(for_accounts(accounts, fn))


def register(root: click.Group) -> None:
    root.add_command(mailbox_group)
