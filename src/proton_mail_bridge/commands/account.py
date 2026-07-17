from __future__ import annotations

import click

from proton_mail_bridge.core.config import (
    Account,
    config_path,
    find_account,
    load_config,
    resolve_config,
    save_config,
)
from proton_mail_bridge.utils import output as out_mod


@click.group("account")
def account_group() -> None:
    """Account registry & identities."""


@account_group.command("list")
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List configured accounts."""
    cfg = load_config(config_path())
    rows = [
        {"email": a.email, "alias": a.alias, "default": a.email == cfg.default_account}
        for a in cfg.accounts
    ]
    out_mod.out({"accounts": rows, "count": len(rows)})


@account_group.command("add-raw")
@click.option("--email", required=True)
@click.option("--password", required=True)
@click.option("--alias", default=None)
@click.pass_context
def add_raw_cmd(ctx: click.Context, email: str, password: str, alias: str | None) -> None:
    """Add an account non-interactively (no login test)."""
    path = config_path()
    cfg = load_config(path)
    if any(a.email == email for a in cfg.accounts):
        out_mod.out_err("config", "Account already exists", email)
    cfg.accounts.append(Account(email=email, password=password, alias=alias))
    cfg.default_account = cfg.default_account or email
    save_config(cfg, path)
    out_mod.out_ok(f"Account {email} added.")


@account_group.command("add")
@click.pass_context
def add_cmd(ctx: click.Context) -> None:
    """Add an account interactively (endpoint wizard on first setup + login test)."""
    path = config_path()
    cfg = load_config(path)
    if not cfg.accounts:
        cfg.endpoint.host = click.prompt("Bridge host", default=cfg.endpoint.host)
        cfg.endpoint.imap_port = click.prompt("IMAP port", default=cfg.endpoint.imap_port, type=int)
        cfg.endpoint.smtp_port = click.prompt("SMTP port", default=cfg.endpoint.smtp_port, type=int)
        cfg.endpoint.security = click.prompt("Security", default=cfg.endpoint.security,
                                             type=click.Choice(["starttls", "ssl"]))
        _autodetect_security(cfg.endpoint)
    email = click.prompt("Email")
    password = click.prompt("Bridge password", hide_input=True)
    alias = click.prompt("Alias (optional)", default="", show_default=False) or None
    if any(a.email == email for a in cfg.accounts):
        out_mod.out_err("config", "Account already exists", email)
    account = Account(email=email, password=password, alias=alias)
    _test_login(cfg.endpoint, account)  # raises on failure
    cfg.accounts.append(account)
    cfg.default_account = cfg.default_account or email
    save_config(cfg, path)
    out_mod.out_ok(f"Account {email} connected and saved.")


@account_group.command("remove")
@click.argument("value")
@click.option("--yes", "assume_yes", is_flag=True)
@click.pass_context
def remove_cmd(ctx: click.Context, value: str, assume_yes: bool) -> None:
    """Remove an account from the registry (🟡)."""
    from proton_mail_bridge.core import guard

    guard.enforce(f"account remove {value}", guard.CONFIRM, assume_yes=assume_yes)
    path = config_path()
    cfg = load_config(path)
    before = len(cfg.accounts)
    removed = find_account(cfg, value)
    cfg.accounts = [a for a in cfg.accounts if a.email != value and a.alias != value]
    if len(cfg.accounts) == before:
        out_mod.out_err("config", "Account not found", value)
    if removed and cfg.default_account == removed.email:
        cfg.default_account = cfg.accounts[0].email if cfg.accounts else None
    save_config(cfg, path)
    out_mod.out_ok(f"Account {value} removed.")


@account_group.command("set-default")
@click.argument("value")
@click.pass_context
def set_default_cmd(ctx: click.Context, value: str) -> None:
    """Set the default account for sending."""
    path = config_path()
    cfg = load_config(path)
    found = find_account(cfg, value)
    if not found:
        out_mod.out_err("config", "Account not found", value)
        return
    cfg.default_account = found.email
    save_config(cfg, path)
    out_mod.out_ok(f"Default account: {found.email}")


@account_group.command("info")
@click.pass_context
def info_cmd(ctx: click.Context) -> None:
    """Folder list + resolved special-use folders per account (Gluon has no QUOTA)."""
    from proton_mail_bridge.core.config import resolve_accounts
    from proton_mail_bridge.core.imap import ImapClient, for_accounts

    cfg = resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")

    def fn(account):
        with ImapClient.connect(cfg.endpoint, account) as c:
            return {"folders": c.list_folders(), "special": c.special_folders()}

    out_mod.out(for_accounts(accounts, fn))


@account_group.command("test")
@click.pass_context
def test_cmd(ctx: click.Context) -> None:
    """IMAP+SMTP login test per account."""
    from proton_mail_bridge.core.config import resolve_accounts
    from proton_mail_bridge.core.imap import for_accounts

    cfg = resolve_config()
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")

    def fn(account):
        _test_login(cfg.endpoint, account)
        return {"imap": "ok", "smtp": "ok"}

    out_mod.out(for_accounts(accounts, fn))


def _autodetect_security(endpoint) -> None:
    """Banner probe per port; corrects the selection when the server speaks differently.
    (macOS Bridge: SMTP often ssl, IMAP starttls — not representable with a single value.)"""
    from proton_mail_bridge.core.connection import detect_security

    imap_mode = detect_security(endpoint.host, endpoint.imap_port)
    if imap_mode and imap_mode != endpoint.security:
        click.echo(f"⚠ IMAP port speaks {imap_mode} — using {imap_mode}.")
        endpoint.security = imap_mode
    smtp_mode = detect_security(endpoint.host, endpoint.smtp_port)
    if smtp_mode and smtp_mode != (endpoint.smtp_security or endpoint.security):
        click.echo(f"⚠ SMTP port speaks {smtp_mode} — using {smtp_mode} (smtp_security).")
        endpoint.smtp_security = smtp_mode


def _test_login(endpoint, account) -> None:
    from proton_mail_bridge.core.imap import ImapClient
    from proton_mail_bridge.core.smtp import SmtpSession

    with ImapClient.connect(endpoint, account):
        pass
    with SmtpSession.connect(endpoint, account):
        pass


def register(root: click.Group) -> None:
    root.add_command(account_group)
