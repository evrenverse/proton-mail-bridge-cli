from __future__ import annotations

import datetime as dt

import pytest

from proton_mail_bridge.utils import otp

# The bodies below are the wording of real verification mail, with the code digits
# changed. The prose is what the extractor has to survive, and guessing it was exactly
# the failure mode this module exists to avoid.

O2 = (
    "Für den Log-In in das Mein o2 Portal Guten Tag, um Ihre Identität zu bestätigen, "
    "geben Sie bitte unter login.o2online.de den folgenden Sicherheitscode ein. "
    "DIESEN CODE BITTE NIEMALS AM TELEFON VORLESEN ODER IN EINEM CHAT WEITERGEBEN. "
    "470600 Falls Sie diesen Vorgang nicht selbst veranlasst haben, ändern Sie bitte "
    "sofort Ihr Kennwort. Telefónica Germany GmbH & Co. OHG Georg-Brauchle-Ring 50 "
    "80992 München Deutschland"
)

VOELKNER = (
    "Bitte geben Sie den folgenden Code ein, um sich in Ihrem Konto anzumelden. "
    "Der Code läuft in 30 Minuten nach Erhalt dieser E-Mail ab. Ihr Verifizierungscode "
    "867674 Gültig bis: 26.08.2026 18:55:09 Mit freundlichen Grüßen Ihr voelkner-Team"
)

KINDE = (
    "Hi there, Please use the code below to confirm your email address and continue on "
    "yell. services. This code will expire in 2 hours. If you don't think you should be "
    "receiving this email, you can safely ignore it. 879997 You received this email "
    "because you requested a confirmation code from yell. services."
)

MICROSOFT = (
    "We received your request for a single-use code to use with your Microsoft account. "
    "Your single-use code is: 169213 Only enter this code on an official website or app. "
    "Don't share it with anyone. Thanks, The Microsoft account team Privacy Statement: "
    "https://go.microsoft.com/fwlink/?LinkId=521839 Microsoft Corporation, "
    "One Microsoft Way, Redmond, WA 98052"
)

INDEED = (
    "Melden Sie sich mit dem einmaligen Passcode an. Verwenden Sie diesen Code, um sich "
    "bei Ihrem Indeed-Konto anzumelden 448497 Gerät Firefox unter Windows Datum "
    "13. August 2026 um 15:46:31 UTC IP-Adresse 87.191.52.218 Standort in der Nähe von "
    "Nuremberg, Germany © 2026 Indeed Ireland Operations Ltd."
)

METRO = (
    "Guten Tag, Bitte gib diesen Code bei der Anmeldung in Deinem myMETRO "
    "Online-Kundenkonto ein. Dein Verifizierungs-Code: 541960 Wenn Du diesen "
    "Verifizierungs-Code nicht angefordert hast, kannst Du diese E-Mail ignorieren oder "
    "Dich an unseren Kundenservice wenden. Mit freundlichen Grüßen, Dein METRO "
    "Kundenservice Bitte antworte nicht auf diese automatische E-Mail. "
    "METRO Deutschland GmbH Metro-Str. 8 40235 Düsseldorf HRB 13665 Amtsgericht "
    "Düsseldorf USt ID: DE184048859"
)


@pytest.mark.parametrize(
    ("name", "subject", "body", "expected"),
    [
        # the code sits behind a warning sentence, and the imprint holds a postal code
        ("o2", "Ihr angeforderter Sicherheitscode", O2, "470600"),
        # the expiry line puts a year next to an hour: `26.08.2026 18:55`
        ("voelkner", "Bitte verifizieren Sie Ihre Anmeldung", VOELKNER, "867674"),
        # 105 characters of boilerplate between the last code word and the code
        ("kinde", "Email verification code", KINDE, "879997"),
        # ZIP code and a six-digit tracking id inside a URL
        ("microsoft", "Your single-use code", MICROSOFT, "169213"),
        # an IP address, a timestamp and a copyright year in the login report
        ("indeed", "Melden Sie sich bei Indeed mit dem folgenden Code an: 448497",
         INDEED, "448497"),
        # commercial register number, VAT id and postal code in the footer
        ("metro", "541960 - Dein METRO Verifizierungs-Code", METRO, "541960"),
    ],
)
def test_real_mail_yields_exactly_one_code(name, subject, body, expected):
    assert otp.extract(subject, body, "") == [expected], name


def test_code_may_be_printed_in_groups():
    """Link prints `582 800`; the groups are joined, because that is what the form takes."""
    assert otp.extract("Ihr Link-Verifizierungscode: 582 800", "", "") == ["582800"]


def test_uneven_groups_are_two_numbers_not_one_code():
    """`Klaus-Conrad-Str. 1 92242 Hirschau` is a house number meeting a postal code."""
    body = ("Nicht mit anderen Codes kombinierbar. Produziert und betreut von: "
            "Conrad Electronic SE Klaus-Conrad-Str. 1 92242 Hirschau")
    assert otp.extract("Vielen Dank für Ihre Treue!", body, "") == []


def test_unanchored_numbers_do_not_exist():
    """Without a code word nearby, nothing counts -- that is the whole first rule."""
    body = ("Ihre Bestellung 303-2980979-4941156 wurde versandt. Rechnungsbetrag 129,90 "
            "EUR. Musterstraße 7, 90402 Nürnberg. Rückfragen unter 0911 1234567.")
    assert otp.extract("Versandbestätigung", body, "") == []


def test_a_year_is_never_a_code():
    assert otp.extract("Ihr Code", "Ihr Verifizierungscode 2026 gilt heute", "") == []


def test_issue_numbers_are_not_codes():
    """GitHub release notes anchor on `Decode`/`Annotation code fix` and are full of #1234."""
    body = ("Bug Fixes Expand low-bit samples for images without a filter ( #3938 ) "
            "Decode low-bit DeviceRGB images as RGB instead of palette ( #3929 )")
    assert otp.extract("[repo] build(deps): bump pypdf", body, "") == []


def test_phone_numbers_are_not_codes():
    """`+49 69 365057560` has even groups, so only the leading `+` tells them apart."""
    body = "Passcode: eZ3Ka6fd Per Telefon einwählen +49 69 365057560 Deutschland"
    assert otp.extract("Online-Kennenlerngespräch", body, "") == []


def test_words_that_end_in_code_do_not_anchor():
    """`Schadcode`, `Rabattcode` and `Reg. code` introduce something, never an OTP."""
    assert otp.extract("Newsletter", "Quelle LiteLLM-Schadcode: 2500 Firmen gefährdet", "") == []
    assert otp.extract("Rechnung", "Bolt Operations OÜ, Tallinn 10134, Reg. code 14532901",
                       "") == []


def test_a_static_pin_does_not_anchor_a_postal_code():
    """`1&1 Service-PIN` sat 60 characters from `56410 Montabaur` in real mail."""
    body = ("Halten Sie bei Anruf bitte Ihre Vertragsdaten und 1&1 Service-PIN bereit. "
            "1&1 Telecom GmbH, Elgendorfer Straße 57, 56410 Montabaur")
    assert otp.extract("Ihre 1&1 Rechnung", body, "") == []


def test_several_candidates_are_reported_and_not_ranked():
    """A discount mailing lists one code per product. Nothing in it says which is meant,
    so the caller gets all of them and may not use any."""
    body = ("10% Rabatt auf Ladungssicherung Code: LASI10 5% Rabatt auf HARDTOPS "
            "Code: HARDTOP5 5% Rabatt auf Pickup-Rollo Code: ROLLO5")
    assert otp.extract("10% Rabatt zu Ostern", body, "") == ["LASI10", "HARDTOP5", "ROLLO5"]


def test_an_imprint_right_behind_the_code_makes_the_message_unusable():
    """The known ceiling of a proximity window, asserted rather than discovered later.

    Real METRO mail puts a paragraph between the code and its imprint, which is why it
    reads cleanly. Strip that paragraph and the postal code and the register number fall
    inside the window -- three candidates, and the caller must refuse all of them. That is
    the intended failure: refusing beats returning `40235`.
    """
    body = ("Dein Verifizierungs-Code: 541960 METRO Deutschland GmbH Metro-Str. 8 "
            "40235 Düsseldorf HRB 13665 Amtsgericht Düsseldorf")
    assert otp.extract("Verifizierungs-Code", body, "") == ["541960", "40235", "13665"]


def test_letters_alone_are_not_a_code():
    """o2's all-caps warning would otherwise supply eight candidates. The price is a
    pure-letter code like Discord's -- a clean miss beats a wrong code in a form."""
    assert otp.extract("Verifizierungscode", "Dein Verifizierungscode lautet BSDTKC", "") == []


def test_alphanumeric_codes_survive():
    assert otp.extract("Code", "Ihr Bestätigungscode lautet A7B2K9", "") == ["A7B2K9"]


def test_the_body_is_read_out_of_html_when_there_is_no_text_part():
    """Most verification mail is HTML-only, and its stylesheet is full of numbers."""
    html = ("<html><head><style>.box{width:480px;height:96px;margin:100px}</style></head>"
            "<body><p>Ihr Verifizierungscode</p><p><b>314159</b></p></body></html>")
    assert otp.extract("Verifizierung", "", html) == ["314159"]


def test_soft_hyphens_between_digits_do_not_split_a_code():
    assert otp.extract("Code", "Ihr Code lautet 44­84­97 heute", "") == ["448497"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("10m", dt.timedelta(minutes=10)), ("2h", dt.timedelta(hours=2)),
     ("1d", dt.timedelta(days=1)), ("45", dt.timedelta(minutes=45))],
)
def test_parse_window(value, expected):
    assert otp.parse_window(value) == expected


@pytest.mark.parametrize("value", ["gestern", "", "0m", "-5m", "10w"])
def test_parse_window_rejects_nonsense(value):
    with pytest.raises(ValueError):
        otp.parse_window(value)


def test_parse_date_assumes_utc_when_the_header_carries_no_offset():
    assert otp.parse_date("2026-08-26T18:55:00").tzinfo is dt.UTC
    assert otp.parse_date("nonsense") is None
    assert otp.parse_date(None) is None


def test_shape_describes_a_code_without_quoting_it():
    assert otp.shape("123456") == "6 digits"
    assert otp.shape("A7B2K9") == "6 characters"
