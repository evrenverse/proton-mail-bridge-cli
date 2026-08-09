from __future__ import annotations

import pytest

from proton_mail_bridge.core import identity as ident
from proton_mail_bridge.core.config import Account, Config, Endpoint, Identity, resolve_accounts
from proton_mail_bridge.core.errors import AccountSelectionError


def _config(accounts, default=None):
    return Config(endpoint=Endpoint(), accounts=accounts, default_account=default)


def test_login_address_is_an_implicit_identity():
    acc = Account("a@p.me", "pw")
    assert [i.email for i in ident.account_identities(acc)] == ["a@p.me"]


def test_explicit_entry_for_login_address_wins():
    acc = Account("a@p.me", "pw", identities=[Identity("a@p.me", name="Chef", label="chef")])
    got = ident.account_identities(acc)
    assert len(got) == 1
    assert got[0].name == "Chef"


def test_default_identity_falls_back_to_login_address():
    acc = Account("a@p.me", "pw", identities=[Identity("k@p.me", label="kontakt")])
    assert ident.default_identity(acc).email == "a@p.me"


def test_default_identity_uses_label():
    acc = Account("a@p.me", "pw", identities=[Identity("k@p.me", label="kontakt")],
                  default_identity="kontakt")
    assert ident.default_identity(acc).email == "k@p.me"


def test_resolve_identity_by_label_picks_the_account():
    c = _config([Account("a@p.me", "1"),
                 Account("b@p.me", "2", identities=[Identity("k@p.me", label="kontakt")])])
    account, found = ident.resolve_identity(c, "kontakt", None)
    assert account.email == "b@p.me"      # kein --account nötig
    assert found.email == "k@p.me"


def test_resolve_identity_by_address():
    c = _config([Account("a@p.me", "1", identities=[Identity("k@p.me")])])
    _, found = ident.resolve_identity(c, "K@P.ME", None)   # Groß-/Kleinschreibung egal
    assert found.email == "k@p.me"


def test_resolve_identity_unknown_lists_known_ones():
    c = _config([Account("a@p.me", "1", identities=[Identity("k@p.me", label="kontakt")])])
    with pytest.raises(AccountSelectionError) as exc:
        ident.resolve_identity(c, "tippfehler", None)
    assert "kontakt" in exc.value.detail
    assert "identity add" in exc.value.detail


def test_unknown_identity_with_account_lists_only_that_account():
    c = _config([Account("a@p.me", "1"),
                 Account("b@p.me", "2", identities=[Identity("k@p.me", label="kontakt")])])
    with pytest.raises(AccountSelectionError) as exc:
        ident.resolve_identity(c, "kontakt", "a@p.me")
    detail = exc.value.detail
    assert "known in a@p.me:" in detail                   # nennt das durchsuchte Konto
    assert "kontakt" not in detail.split("known", 1)[1]   # nicht zugleich unbekannt und bekannt
    assert "k@p.me" not in detail                         # fremdes Konto bleibt draußen


def test_resolve_identity_ambiguous_requires_account():
    c = _config([Account("a@p.me", "1", identities=[Identity("k@p.me", label="kontakt")]),
                 Account("b@p.me", "2", identities=[Identity("k2@p.me", label="kontakt")])])
    with pytest.raises(AccountSelectionError) as exc:
        ident.resolve_identity(c, "kontakt", None)
    assert "--account" in exc.value.detail
    account, _ = ident.resolve_identity(c, "kontakt", "b@p.me")
    assert account.email == "b@p.me"


def test_resolve_identity_without_arg_uses_account_default():
    c = _config([Account("a@p.me", "1", identities=[Identity("k@p.me", label="kontakt")],
                         default_identity="kontakt")], default="a@p.me")
    account, found = ident.resolve_identity(c, None, None)
    assert (account.email, found.email) == ("a@p.me", "k@p.me")


def test_resolve_identity_without_accounts_errors():
    with pytest.raises(AccountSelectionError):
        ident.resolve_identity(_config([]), None, None)


def test_from_with_an_identity_value_hints_at_identity_flag():
    c = _config([Account("a@p.me", "1", identities=[Identity("k@p.me", label="kontakt")])])
    with pytest.raises(AccountSelectionError) as exc:
        resolve_accounts(c, "kontakt", mode="send")
    assert "--identity" in exc.value.detail


def test_unknown_value_still_reports_unknown_account():
    c = _config([Account("a@p.me", "1")])
    with pytest.raises(AccountSelectionError) as exc:
        resolve_accounts(c, "nirgends", mode="send")
    assert exc.value.title == "Unknown account"


def test_pick_reply_identity_uses_the_addressed_address():
    acc = Account("a@p.me", "pw", identities=[Identity("k@p.me", label="kontakt")])
    original = {"to": ["k@p.me", "wer@x.de"], "cc": [], "headers": {}}
    assert ident.pick_reply_identity(acc, original).email == "k@p.me"


def test_pick_reply_identity_checks_cc_and_delivered_to():
    acc = Account("a@p.me", "pw", identities=[Identity("k@p.me")])
    via_cc = {"to": ["wer@x.de"], "cc": ["k@p.me"], "headers": {}}
    assert ident.pick_reply_identity(acc, via_cc).email == "k@p.me"
    via_header = {"to": ["wer@x.de"], "cc": [],
                  "headers": {"delivered-to": ["Kontakt <k@p.me>"]}}
    assert ident.pick_reply_identity(acc, via_header).email == "k@p.me"


def test_pick_reply_identity_falls_back_to_default():
    acc = Account("a@p.me", "pw", identities=[Identity("k@p.me", label="kontakt")],
                  default_identity="kontakt")
    original = {"to": ["fremd@x.de"], "cc": [], "headers": {}}
    assert ident.pick_reply_identity(acc, original).email == "k@p.me"


def test_own_addresses_covers_all_identities():
    acc = Account("A@p.me", "pw", identities=[Identity("K@p.me")])
    assert ident.own_addresses(acc) == {"a@p.me", "k@p.me"}
