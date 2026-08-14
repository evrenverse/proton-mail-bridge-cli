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
    """List configured accounts including their sender identities."""
    from proton_mail_bridge.core.identity import account_identities

    cfg = load_config(config_path())
    rows = [
        {
            "email": a.email,
            "alias": a.alias,
            "default": a.email == cfg.default_account,
            "default_identity": a.default_identity,
            "identities": [
                {"email": i.email, "name": i.name, "label": i.label}
                for i in account_identities(a)
            ],
        }
        for a in cfg.accounts
    ]
    out_mod.out({"accounts": rows, "count": len(rows)})


@account_group.command("add-raw")
@click.option("--email", required=True)
@click.option("--password", required=True)
@click.option("--alias", default=None)
@out_mod.dry_run_option
@click.pass_context
def add_raw_cmd(
    ctx: click.Context, email: str, password: str, alias: str | None, dry_run: bool
) -> None:
    """Add an account non-interactively (no login test)."""
    path = config_path()
    cfg = load_config(path)
    if any(a.email == email for a in cfg.accounts):
        out_mod.out_err("config", "Account already exists", email)
    if dry_run:
        out_mod.out_plan("account add-raw", {
            "account": email, "alias": alias,
            "default_account": cfg.default_account or email, "config": str(path),
        })
        return
    cfg.accounts.append(Account(email=email, password=password, alias=alias))
    cfg.default_account = cfg.default_account or email
    save_config(cfg, path)
    out_mod.out_ok(f"Account {email} added.")


@account_group.command("add")
@out_mod.dry_run_option
@click.pass_context
def add_cmd(ctx: click.Context, dry_run: bool) -> None:
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
    if dry_run:
        # the login test already ran: the dry run confirms the credentials, it just stores nothing
        out_mod.out_plan("account add", {
            "account": email, "alias": alias, "login": "ok",
            "default_account": cfg.default_account or email, "config": str(path),
        })
        return
    cfg.accounts.append(account)
    cfg.default_account = cfg.default_account or email
    save_config(cfg, path)
    out_mod.out_ok(f"Account {email} connected and saved.")


@account_group.command("remove")
@click.argument("value")
@click.option("--yes", "assume_yes", is_flag=True)
@out_mod.dry_run_option
@click.pass_context
def remove_cmd(ctx: click.Context, value: str, assume_yes: bool, dry_run: bool) -> None:
    """Remove an account from the registry (🟡)."""
    from proton_mail_bridge.core import guard

    if not dry_run:
        guard.enforce(f"account remove {value}", guard.CONFIRM, assume_yes=assume_yes)
    path = config_path()
    cfg = load_config(path)
    before = len(cfg.accounts)
    removed = find_account(cfg, value)
    if dry_run:
        if not removed:
            out_mod.out_err("config", "Account not found", value)
            return
        rest = [a for a in cfg.accounts if a is not removed]
        out_mod.out_plan("account remove", {
            "account": removed.email, "alias": removed.alias, "risk": guard.CONFIRM,
            "identities": [i.email for i in removed.identities],
            "new_default_account": (
                (rest[0].email if rest else None)
                if cfg.default_account == removed.email else cfg.default_account
            ),
            "config": str(path),
        })
        return
    cfg.accounts = [a for a in cfg.accounts if a.email != value and a.alias != value]
    if len(cfg.accounts) == before:
        out_mod.out_err("config", "Account not found", value)
    if removed and cfg.default_account == removed.email:
        cfg.default_account = cfg.accounts[0].email if cfg.accounts else None
    save_config(cfg, path)
    out_mod.out_ok(f"Account {value} removed.")


@account_group.command("set-default")
@click.argument("value")
@out_mod.dry_run_option
@click.pass_context
def set_default_cmd(ctx: click.Context, value: str, dry_run: bool) -> None:
    """Set the default account for sending."""
    path = config_path()
    cfg = load_config(path)
    found = find_account(cfg, value)
    if not found:
        out_mod.out_err("config", "Account not found", value)
        return
    if dry_run:
        out_mod.out_plan("account set-default", {
            "default_account": found.email, "previous": cfg.default_account,
            "config": str(path),
        })
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


@account_group.group("identity")
def identity_group() -> None:
    """Sender identities (own addresses) of an account."""


@identity_group.command("add")
@click.option("--email", required=True)
@click.option("--name", default=None, help="Display name for the From header.")
@click.option("--label", default=None, help="Short handle for `--identity`.")
@out_mod.dry_run_option
@click.pass_context
def identity_add_cmd(
    ctx: click.Context, email: str, name: str | None, label: str | None, dry_run: bool
) -> None:
    """Add a sender identity to an account (🟢)."""
    from proton_mail_bridge.core.config import Identity, resolve_accounts

    path = config_path()
    cfg = load_config(path)
    account = resolve_accounts(cfg, ctx.obj.get("account"), mode="send")[0]
    needle = email.strip().lower()
    if account.email.lower() == needle or any(
        i.email.lower() == needle for i in account.identities
    ):
        out_mod.out_err("config", "Identity already exists", email)
    if label and any(
        i.label and i.label.lower() == label.strip().lower() for i in account.identities
    ):
        out_mod.out_err("config", "Label already used", label)
    if dry_run:
        out_mod.out_plan("account identity add", {
            "account": account.email, "identity": email, "name": name, "label": label,
            "config": str(path),
        })
        return
    account.identities.append(Identity(email=email, name=name, label=label))
    save_config(cfg, path)
    out_mod.out_ok(f"Identity {email} added to {account.email}.")


@identity_group.command("remove")
@click.argument("value")
@click.option("--yes", "assume_yes", is_flag=True)
@out_mod.dry_run_option
@click.pass_context
def identity_remove_cmd(
    ctx: click.Context, value: str, assume_yes: bool, dry_run: bool
) -> None:
    """Remove a sender identity (🟡)."""
    from proton_mail_bridge.core import guard
    from proton_mail_bridge.core.identity import resolve_identity

    if not value.strip():
        out_mod.out_err("config", "Identity value required", "VALUE must not be blank.")
    if not dry_run:
        guard.enforce(f"account identity remove {value}", guard.CONFIRM, assume_yes=assume_yes)
    path = config_path()
    cfg = load_config(path)
    account, found = resolve_identity(cfg, value, ctx.obj.get("account"))
    if not any(i is found for i in account.identities):
        out_mod.out_err(
            "config",
            "Cannot remove that identity",
            f"{found.email} is the account's own Bridge login address.",
        )
    stale = {found.email.lower()}
    if found.label:
        stale.add(found.label.lower())
    clears_default = bool(
        account.default_identity and account.default_identity.lower() in stale
    )
    if dry_run:
        out_mod.out_plan("account identity remove", {
            "account": account.email, "identity": found.email, "label": found.label,
            "risk": guard.CONFIRM, "clears_default_identity": clears_default,
            "config": str(path),
        })
        return
    account.identities = [i for i in account.identities if i is not found]
    if clears_default:
        account.default_identity = None
    save_config(cfg, path)
    out_mod.out_ok(f"Identity {found.email} removed from {account.email}.")


@identity_group.command("set-default")
@click.argument("value")
@out_mod.dry_run_option
@click.pass_context
def identity_set_default_cmd(ctx: click.Context, value: str, dry_run: bool) -> None:
    """Set the default sender identity of an account."""
    from proton_mail_bridge.core.identity import resolve_identity

    if not value.strip():
        out_mod.out_err("config", "Identity value required", "VALUE must not be blank.")
    path = config_path()
    cfg = load_config(path)
    account, found = resolve_identity(cfg, value, ctx.obj.get("account"))
    if dry_run:
        out_mod.out_plan("account identity set-default", {
            "account": account.email, "default_identity": found.label or found.email,
            "address": found.email, "previous": account.default_identity,
            "config": str(path),
        })
        return
    account.default_identity = found.label or found.email
    save_config(cfg, path)
    out_mod.out_ok(f"Default identity of {account.email}: {found.email}")


@identity_group.command("discover")
@click.option("--limit", default=300, show_default=True,
              help="How many Sent messages to scan per account.")
@click.option("--save", "do_save", is_flag=True, help="Write unknown addresses to the config.")
@click.pass_context
def identity_discover_cmd(ctx: click.Context, limit: int, do_save: bool) -> None:
    """Find sender addresses by scanning the Sent folder (🟢).

    The Bridge accepts every MAIL FROM and only validates at send time, so the Sent
    folder is the only reliable source for which addresses this account can send from.
    """
    from proton_mail_bridge.core.config import Identity, resolve_accounts
    from proton_mail_bridge.core.errors import BridgeError
    from proton_mail_bridge.core.identity import account_identities, group_senders
    from proton_mail_bridge.core.imap import ImapClient, for_accounts

    path = config_path()
    cfg = load_config(path)          # the file we mutate and save
    endpoint = resolve_config().endpoint  # env overrides apply to the connection
    accounts = resolve_accounts(cfg, ctx.obj.get("account"), mode="read")

    def fn(account):
        with ImapClient.connect(endpoint, account) as c:
            # Never fall back to INBOX: there the From headers belong to the senders,
            # and --save would store every correspondent as our own identity.
            folder = c.special_folders().get("sent")
            if not folder:
                raise BridgeError(
                    "config",
                    "No Sent folder found",
                    "The account exposes no \\Sent special-use folder — cannot discover "
                    "sender addresses. Add identities manually with `account identity add`.",
                )
            senders = group_senders(c.sender_addresses(folder, limit))
        known = {i.email.lower() for i in account_identities(account)}
        added: list[str] = []
        for rec in senders:
            rec["known"] = rec["email"].lower() in known
            if do_save and not rec["known"]:
                account.identities.append(Identity(email=rec["email"], name=rec["name"]))
                added.append(rec["email"])
        return {"folder": folder, "senders": senders, "added": added}

    results = for_accounts(accounts, fn)
    if do_save and any(r.get("items", {}).get("added") for r in results):
        save_config(cfg, path)
    out_mod.out(results)


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
