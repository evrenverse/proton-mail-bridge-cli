from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from proton_mail_bridge.core.errors import AccountSelectionError

DEFAULT_IMAP_PORT = 1143
DEFAULT_SMTP_PORT = 1025


@dataclass
class Endpoint:
    host: str = "127.0.0.1"
    imap_port: int = DEFAULT_IMAP_PORT
    smtp_port: int = DEFAULT_SMTP_PORT
    security: str = "starttls"  # "starttls" | "ssl" (IMAP; default for SMTP)
    # The macOS Bridge often runs SMTP in SSL mode while IMAP stays starttls → separate setting.
    smtp_security: str | None = None  # None = same as security
    tls_cert_path: str | None = None
    timeout: float = 30.0  # socket timeout in seconds (IMAP+SMTP); hanging is not an agent option


@dataclass
class Account:
    email: str
    password: str
    alias: str | None = None


@dataclass
class Config:
    endpoint: Endpoint = field(default_factory=Endpoint)
    accounts: list[Account] = field(default_factory=list)
    default_account: str | None = None


def config_path(env: Mapping[str, str] | None = None) -> Path:
    env = env if env is not None else os.environ
    override = env.get("PROTON_BRIDGE_CONFIG")
    if override:
        return Path(override)
    xdg = env.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "proton-mail-bridge" / "config.toml"
    if os.name == "nt":
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / ".config"
        return base / "proton-mail-bridge" / "config.toml"
    return Path.home() / ".config" / "proton-mail-bridge" / "config.toml"


def _load_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_config(path: Path | None = None) -> Config:
    path = path if path is not None else config_path()
    raw = _load_file(path)
    ep = raw.get("endpoint", {})
    endpoint = Endpoint(
        host=ep.get("host", "127.0.0.1"),
        imap_port=int(ep.get("imap_port", DEFAULT_IMAP_PORT)),
        smtp_port=int(ep.get("smtp_port", DEFAULT_SMTP_PORT)),
        security=ep.get("security", "starttls"),
        smtp_security=ep.get("smtp_security"),
        tls_cert_path=ep.get("tls_cert_path"),
        timeout=float(ep.get("timeout", 30.0)),
    )
    accounts = [
        Account(email=a["email"], password=a.get("password", ""), alias=a.get("alias"))
        for a in raw.get("accounts", [])
    ]
    return Config(endpoint=endpoint, accounts=accounts, default_account=raw.get("default_account"))


def resolve_config(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
    load_file: bool = True,
) -> Config:
    """Load the config file, then layer env vars on top (env > file > defaults)."""
    env = env if env is not None else os.environ
    config = load_config(path) if load_file else Config()

    ep = config.endpoint
    if "PROTON_BRIDGE_HOST" in env:
        ep.host = env["PROTON_BRIDGE_HOST"]
    if "PROTON_BRIDGE_IMAP_PORT" in env:
        ep.imap_port = int(env["PROTON_BRIDGE_IMAP_PORT"])
    # SMTP port: the new name wins, otherwise the legacy alias PROTON_BRIDGE_PORT
    if "PROTON_BRIDGE_SMTP_PORT" in env:
        ep.smtp_port = int(env["PROTON_BRIDGE_SMTP_PORT"])
    elif "PROTON_BRIDGE_PORT" in env:
        ep.smtp_port = int(env["PROTON_BRIDGE_PORT"])
    if "PROTON_BRIDGE_SECURITY" in env:
        ep.security = env["PROTON_BRIDGE_SECURITY"]

    user = env.get("PROTON_BRIDGE_USER")
    password = env.get("PROTON_BRIDGE_PASS")
    if user and password:
        existing = find_account(config, user)
        if existing:
            existing.password = password
        else:
            config.accounts.insert(0, Account(email=user, password=password))
        config.default_account = config.default_account or user
    if "PROTON_BRIDGE_ACCOUNT" in env:
        config.default_account = env["PROTON_BRIDGE_ACCOUNT"]
    return config


def save_config(config: Config, path: Path | None = None) -> Path:
    import tomli_w

    path = path if path is not None else config_path()
    data: dict = {
        "endpoint": {
            "host": config.endpoint.host,
            "imap_port": config.endpoint.imap_port,
            "smtp_port": config.endpoint.smtp_port,
            "security": config.endpoint.security,
            "timeout": config.endpoint.timeout,
        },
        "accounts": [
            {k: v for k, v in {"email": a.email, "password": a.password, "alias": a.alias}.items()
             if v is not None}
            for a in config.accounts
        ],
    }
    if config.endpoint.smtp_security:
        data["endpoint"]["smtp_security"] = config.endpoint.smtp_security
    if config.endpoint.tls_cert_path:
        data["endpoint"]["tls_cert_path"] = config.endpoint.tls_cert_path
    if config.default_account:
        data["default_account"] = config.default_account
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)
    try:
        path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass
    return path


def find_account(config: Config, value: str) -> Account | None:
    for a in config.accounts:
        if a.email == value or (a.alias and a.alias == value):
            return a
    return None


def resolve_accounts(config: Config, account_arg: str | None, mode: str) -> list[Account]:
    """Account selection per command type.

    mode: "read" (fan-out default), "identity" (sending: default_account allowed),
    "message_op" (UID ops: no default_account fallback).
    """
    if not config.accounts:
        raise AccountSelectionError(
            "auth",
            "No account configured",
            "Run `proton-mail-bridge account add`.",
        )
    if account_arg == "all":
        return list(config.accounts)
    if account_arg:
        found = find_account(config, account_arg)
        if not found:
            raise AccountSelectionError("auth", "Unknown account", account_arg)
        return [found]

    if mode == "read":
        return list(config.accounts)

    # identity / message_op: exactly one account required
    if mode == "identity" and config.default_account:
        found = find_account(config, config.default_account)
        if found:
            return [found]
    if len(config.accounts) == 1:
        return [config.accounts[0]]
    raise AccountSelectionError(
        "auth",
        "Multiple accounts, none selected",
        "pass --account"
        + (" or set one via `account set-default`" if mode == "identity" else ""),
    )
