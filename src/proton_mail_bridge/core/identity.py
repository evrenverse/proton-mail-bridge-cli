from __future__ import annotations

from proton_mail_bridge.core.config import Account, Config, Identity, resolve_accounts
from proton_mail_bridge.core.errors import AccountSelectionError


def account_identities(account: Account) -> list[Identity]:
    """All sender identities of an account, including the implicit login address.

    The login address is always usable as a sender. An explicit entry for it wins,
    so a display name configured for the login address is preserved.
    """
    login = account.email.lower()
    if any(i.email.lower() == login for i in account.identities):
        return list(account.identities)
    return [Identity(email=account.email), *account.identities]


def match_identity(identities: list[Identity], value: str) -> Identity | None:
    """Match by e-mail address or label, case-insensitively."""
    needle = value.strip().lower()
    for i in identities:
        if i.email.lower() == needle or (i.label and i.label.lower() == needle):
            return i
    return None


def default_identity(account: Account) -> Identity:
    """`default_identity` of the account, otherwise its login address."""
    identities = account_identities(account)
    if account.default_identity:
        found = match_identity(identities, account.default_identity)
        if found:
            return found
    return match_identity(identities, account.email) or Identity(email=account.email)


def known_identity_names(config: Config) -> list[str]:
    """Labels (or addresses, when unlabelled) of every identity — for error messages."""
    return [i.label or i.email for a in config.accounts for i in account_identities(a)]


def resolve_identity(
    config: Config, identity_arg: str | None, account_arg: str | None
) -> tuple[Account, Identity]:
    """Sender selection: `--identity` alone determines account and sender address.

    Without `--identity` the account is resolved as before and its default identity used.
    """
    if not config.accounts:
        raise AccountSelectionError(
            "auth", "No account configured", "Run `proton-mail-bridge account add`."
        )
    if not identity_arg:
        account = resolve_accounts(config, account_arg, mode="send")[0]
        return account, default_identity(account)

    pool = resolve_accounts(config, account_arg, mode="send") if account_arg else config.accounts
    hits: list[tuple[Account, Identity]] = []
    for account in pool:
        found = match_identity(account_identities(account), identity_arg)
        if found:
            hits.append((account, found))
    if not hits:
        raise AccountSelectionError(
            "config",
            "Unknown identity",
            f"{identity_arg} — known: {', '.join(known_identity_names(config))}. "
            "Add it with `account identity add`.",
        )
    if len(hits) > 1:
        owners = ", ".join(a.email for a, _ in hits)
        raise AccountSelectionError(
            "config", "Ambiguous identity", f"{identity_arg} exists in {owners} — pass --account."
        )
    return hits[0]
