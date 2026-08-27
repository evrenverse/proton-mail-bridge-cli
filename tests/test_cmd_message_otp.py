from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint
from proton_mail_bridge.core.imap import ImapClient
from tests.conftest import FakeMailBox, FakeMessage

CODE_MAIL = (
    "Bitte geben Sie den folgenden Code ein, um sich anzumelden. Der Code läuft in 30 "
    "Minuten ab. Ihr Verifizierungscode 867674 Gültig bis: 26.08.2026 18:55:09"
)


def _mail(uid: str, *, minutes_ago: float, text: str, subject: str = "Ihre Anmeldung",
          from_: str = "noreply@voelkner.de") -> FakeMessage:
    when = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return FakeMessage(
        uid=uid, subject=subject, from_=from_, date=when,
        date_str=when.strftime("%a, %d %b %Y %H:%M:%S %z"), text=text, html="",
        headers={"message-id": (f"<{uid}@voelkner.de>",)}, attachments=[],
    )


def _patch(monkeypatch, store, *, accounts=None, folder_flags=None):
    accounts = accounts or [Account("a@p.me", "1")]
    monkeypatch.setattr(
        cfgmod, "resolve_config",
        lambda *a, **k: Config(Endpoint(), accounts, accounts[0].email),
    )
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(
            FakeMailBox(dict(store), folder_flags), acc.email)),
    )


def _run(*args):
    return CliRunner().invoke(main, ["--json", "message", "otp", *args])


def test_returns_the_code_of_a_fresh_message(monkeypatch):
    _patch(monkeypatch, {"INBOX": [_mail("1", minutes_ago=2, text=CODE_MAIL)]})
    result = _run()
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["code"] == "867674"
    assert data["from"] == "noreply@voelkner.de"
    assert data["ambiguous"] is False and data["also_found"] == []
    assert data["age_seconds"] < 200


def test_spam_is_searched_too(monkeypatch):
    """Verification mail lands in Spam often enough that an agent would otherwise stall."""
    _patch(
        monkeypatch,
        {"INBOX": [], "Spam": [_mail("7", minutes_ago=1, text=CODE_MAIL)]},
        folder_flags={"Spam": ("\\Junk",)},
    )
    result = _run()
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["code"] == "867674"
    assert data["folder"] == "Spam"
    assert data["folders"] == ["INBOX", "Spam"]


def test_a_code_from_yesterday_is_not_a_code(monkeypatch):
    """Freshness is part of correctness: the message is there, the window is not."""
    _patch(monkeypatch, {"INBOX": [_mail("1", minutes_ago=60 * 26, text=CODE_MAIL)]})
    result = _run()
    assert result.exit_code == 1
    error = json.loads(result.output)["error"]
    assert error["type"] == "otp_not_found"
    assert "867674" not in result.output


def test_nothing_in_the_window(monkeypatch):
    _patch(monkeypatch, {"INBOX": []})
    result = _run()
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["type"] == "otp_not_found"


def test_an_order_number_is_not_a_code(monkeypatch):
    """The mail is fresh and full of digits -- none of them next to a code word."""
    body = ("Ihre Bestellung 303-2980979-4941156 wurde versandt. Rechnungsbetrag "
            "129,90 EUR. Musterstraße 7, 90402 Nürnberg.")
    _patch(monkeypatch, {"INBOX": [_mail("1", minutes_ago=1, text=body,
                                         subject="Versandbestätigung")]})
    result = _run()
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["type"] == "otp_not_found"


def test_the_newest_message_wins_and_the_others_are_reported(monkeypatch):
    older = _mail("1", minutes_ago=8, text=CODE_MAIL.replace("867674", "111111"))
    newer = _mail("2", minutes_ago=1, text=CODE_MAIL.replace("867674", "222222"))
    _patch(monkeypatch, {"INBOX": [older, newer]})
    result = _run()
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["code"] == "222222"
    assert data["ambiguous"] is True
    assert [e["uid"] for e in data["also_found"]] == ["1"]
    # the displaced code is described, never quoted
    assert data["also_found"][0]["shape"] == "6 digits"
    assert "111111" not in result.output


def test_a_message_with_several_candidates_is_refused(monkeypatch):
    """Nothing in such a message says which candidate the form wants, so none is used."""
    body = ("10% Rabatt auf Ladungssicherung Code: LASI10 5% Rabatt auf HARDTOPS "
            "Code: HARDTOP5 5% Rabatt auf Pickup-Rollo Code: ROLLO5")
    _patch(monkeypatch, {"INBOX": [_mail("1", minutes_ago=1, text=body,
                                         subject="10% Rabatt")]})
    result = _run()
    assert result.exit_code == 1
    error = json.loads(result.output)["error"]
    assert error["type"] == "otp_ambiguous"
    for candidate in ("LASI10", "HARDTOP5", "ROLLO5"):
        assert candidate not in result.output


def test_no_candidate_ever_reaches_a_failing_output(monkeypatch):
    """The one rule that outranks helpfulness: an error may say what it found, not what
    the code is. Subjects are left out too -- senders put the code in them."""
    loud = _mail("1", minutes_ago=1, text=CODE_MAIL,
                 subject="Ihr Verifizierungscode 867674")
    _patch(monkeypatch, {"INBOX": [loud]})
    result = CliRunner().invoke(main, ["--json", "message", "otp", "--since", "0m"])
    assert result.exit_code == 2  # 0m is not a window
    assert "867674" not in result.output


def test_plain_output_is_the_bare_code(monkeypatch):
    """`pmb message otp | …` has to be the whole story, so stdout carries nothing else."""
    _patch(monkeypatch, {"INBOX": [_mail("1", minutes_ago=1, text=CODE_MAIL)]})
    result = CliRunner().invoke(main, ["message", "otp"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "867674"
    assert "voelkner" in result.stderr  # context goes to stderr
    assert "867674" not in result.stderr


def test_since_must_be_a_duration(monkeypatch):
    _patch(monkeypatch, {"INBOX": []})
    result = _run("--since", "gestern")
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["title"] == "Invalid --since"


def test_from_narrows_an_ambiguous_window(monkeypatch):
    shop = _mail("1", minutes_ago=2, text=CODE_MAIL)
    other = _mail("2", minutes_ago=1, text=CODE_MAIL.replace("867674", "999999"),
                  from_="security@example.com")
    _patch(monkeypatch, {"INBOX": [shop, other]})
    assert json.loads(_run().output)["code"] == "999999"  # newest of the two
    narrowed = json.loads(_run("--from", "voelkner.de").output)
    assert narrowed["code"] == "867674" and narrowed["ambiguous"] is False


def test_fan_out_covers_every_account(monkeypatch):
    """Without --account the command reads every account, like search and list do."""
    _patch(monkeypatch, {"INBOX": [_mail("1", minutes_ago=1, text=CODE_MAIL)]},
           accounts=[Account("a@p.me", "1"), Account("b@p.me", "2")])
    data = json.loads(_run().output)
    # both accounts serve the same fake mailbox, so the second copy shows up as displaced
    assert data["code"] == "867674"
    assert {data["account"], *(e["account"] for e in data["also_found"])} == {"a@p.me", "b@p.me"}


def test_a_filtered_away_mail_is_found_in_all_mail(monkeypatch):
    """Measured against a real mailbox: a Proton filter had moved an Indeed login code
    into `Folders/Indeed`, so INBOX and Spam held nothing at all. All Mail is the one
    scope that cannot miss a folder, and it is scanned only when the other two fail."""
    filtered = _mail("9", minutes_ago=1, text=CODE_MAIL, from_="login@indeed.com")
    _patch(
        monkeypatch,
        {"INBOX": [], "Spam": [], "Folders/Indeed": [filtered], "All Mail": [filtered]},
        folder_flags={"Spam": ("\\Junk",), "All Mail": ("\\All",)},
    )
    result = _run()
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["code"] == "867674"
    assert data["folders"] == ["All Mail", "INBOX", "Spam"]  # reported sorted
    assert data["folder"] == "All Mail"


def test_all_mail_stays_unscanned_when_the_inbox_answers(monkeypatch):
    """The fallback is paid for only on the path that was about to fail."""
    _patch(
        monkeypatch,
        {"INBOX": [_mail("1", minutes_ago=1, text=CODE_MAIL)], "Spam": [], "All Mail": []},
        folder_flags={"Spam": ("\\Junk",), "All Mail": ("\\All",)},
    )
    data = json.loads(_run().output)
    assert data["code"] == "867674"
    assert data["folders"] == ["INBOX", "Spam"]


def test_an_explicit_folder_is_not_widened(monkeypatch):
    """--folder is an instruction, not a starting point."""
    _patch(
        monkeypatch,
        {"INBOX": [], "Spam": [], "All Mail": [_mail("1", minutes_ago=1, text=CODE_MAIL)]},
        folder_flags={"Spam": ("\\Junk",), "All Mail": ("\\All",)},
    )
    result = _run("--folder", "INBOX")
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["type"] == "otp_not_found"
