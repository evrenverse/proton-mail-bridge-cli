from __future__ import annotations

from email.utils import parseaddr

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


def known_identity_names(accounts: list[Account]) -> list[str]:
    """Labels (or addresses, when unlabelled) of every identity in `accounts` — error messages."""
    return [i.label or i.email for a in accounts for i in account_identities(a)]


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
        # Scoped to the pool: listing identities of accounts that were not searched would
        # declare the very value unknown and known at once.
        known = known_identity_names(pool)
        scope = f" in {', '.join(a.email for a in pool)}" if account_arg else ""
        raise AccountSelectionError(
            "config",
            "Unknown identity",
            f"{identity_arg} — known{scope}: {', '.join(known)}. "
            "Add it with `account identity add`.",
        )
    if len(hits) > 1:
        owners = ", ".join(a.email for a, _ in hits)
        raise AccountSelectionError(
            "config", "Ambiguous identity", f"{identity_arg} exists in {owners} — pass --account."
        )
    return hits[0]


def own_addresses(account: Account) -> set[str]:
    """Every sender address of the account, lower-cased — for self-filtering on reply-all."""
    return {i.email.lower() for i in account_identities(account)}


def pick_reply_identity(account: Account, original: dict) -> Identity:
    """The identity the original message was addressed to; falls back to the default.

    Checks To, Cc and the Delivered-To/X-Original-To headers in that order.
    """
    identities = account_identities(account)
    by_address = {i.email.lower(): i for i in identities}
    headers = original.get("headers") or {}
    delivered = [
        value
        for key in ("delivered-to", "x-original-to")
        for value in (headers.get(key) or ())
    ]
    for raw in [*(original.get("to") or []), *(original.get("cc") or []), *delivered]:
        address = (parseaddr(raw)[1] or "").strip().lower()
        if address in by_address:
            return by_address[address]
    return default_identity(account)


def group_senders(pairs: list[tuple[str, str]]) -> list[dict]:
    """(display name, address) pairs → [{"email", "name", "count"}], most frequent first.

    `name` is the most common non-empty display name seen for that address.
    """
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    names: dict[str, dict[str, int]] = {}
    for name, raw in pairs:
        address = (parseaddr(raw)[1] or raw).strip()
        if "@" not in address:
            continue
        key = address.lower()
        display.setdefault(key, address)
        counts[key] = counts.get(key, 0) + 1
        if name:
            names.setdefault(key, {})
            names[key][name] = names[key].get(name, 0) + 1
    result: list[dict] = []
    for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        seen = names.get(key, {})
        best = max(seen.items(), key=lambda kv: (kv[1], kv[0]))[0] if seen else None
        result.append({"email": display[key], "name": best, "count": count})
    return result
