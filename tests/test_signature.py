from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core import config as cfgmod
from proton_mail_bridge.core.config import Account, Config, Endpoint, Identity
from proton_mail_bridge.core.errors import BridgeError
from proton_mail_bridge.core.smtp import SmtpSession
from proton_mail_bridge.utils import mime, signature

# What Proton Mail actually puts into a sent message: the user's signature and the
# "Sent with Proton Mail" footer live in sibling divs of the same block.
PROTON_HTML = (
    "<div>Hallo,<br>bis morgen.</div><div><br></div>"
    '<div class="protonmail_signature_block">'
    '<div class="protonmail_signature_block-user">'
    "Evren Tiras<br>Gesch&auml;ftsf&uuml;hrer &amp; Co."
    "</div>"
    '<div class="protonmail_signature_block-proton">'
    'Sent with <a href="https://proton.me/">Proton Mail</a> secure email.'
    "</div>"
    "</div>"
)

# What an address without a configured signature looks like on the wire.
EMPTY_BLOCK = (
    '<div class="protonmail_signature_block">'
    '<div class="protonmail_signature_block-user protonmail_signature_block-empty">'
    "\r\n\r\n            </div>"
    '<div class="protonmail_signature_block-proton protonmail_signature_block-empty">'
    "\r\n\r\n            </div>"
    "</div>"
)


# --- appending ------------------------------------------------------------------


def test_text_signature_uses_the_rfc_separator():
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="Hallo", body_html=None, attachments=None, signature="Evren\nCEO",
    )
    assert msg.get_content() == "Hallo\n\n-- \nEvren\nCEO\n"


def test_signature_survives_an_empty_body():
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="", body_html=None, attachments=None, signature="Evren",
    )
    assert msg.get_content() == "-- \nEvren\n"


def test_html_signature_lands_in_the_html_part():
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="Hallo", body_html="<p>Hallo</p>", attachments=None,
        signature="Evren", signature_html="<b>Evren</b>",
    )
    html = msg.get_body(preferencelist=("html",)).get_content()
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "<b>Evren</b>" in html
    assert "-- \nEvren" in text


def test_an_html_signature_adds_the_html_part_to_a_plain_send():
    """A logo only travels as markup, so the HTML signature must not wait for --html-file
    — otherwise every mail this CLI generates from plain text loses it."""
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="Hallo & tschüss\nbis morgen", body_html=None, attachments=None,
        signature="Evren", signature_html="<b>Evren</b>",
    )
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "Hallo &amp; tschüss<br>\nbis morgen" in html   # the body is escaped, not markup
    assert "<b>Evren</b>" in html
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert text == "Hallo & tschüss\nbis morgen\n\n-- \nEvren\n"


def test_without_an_html_signature_a_plain_send_stays_plain():
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="Hallo", body_html=None, attachments=None, signature="Evren",
    )
    assert not msg.is_multipart()


def test_a_signature_image_travels_as_an_inline_part():
    """The `cid:` in the signature has to resolve inside the message we send — a
    reference to the image of the *source* mail is exactly the invisible logo."""
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="Hallo", body_html=None, attachments=None,
        signature="Evren", signature_html='<img src="cid:k.sig.0.png">',
        signature_images=[("k.sig.0.png", b"\x89PNG", "image/png")],
    )
    parts = {p.get("Content-ID"): p.get_content_type() for p in msg.walk()}
    assert parts["<k.sig.0.png>"] == "image/png"
    assert 'src="cid:k.sig.0.png"' in msg.get_body(preferencelist=("html",)).get_content()


# --- loading --------------------------------------------------------------------


def test_load_reads_both_files(tmp_path):
    (tmp_path / "k.sig").write_text("Evren\nCEO", encoding="utf-8")
    (tmp_path / "k.html").write_text("<b>Evren</b>", encoding="utf-8")
    ident = Identity("k@p.me", signature_file="k.sig", signature_html_file="k.html")
    assert signature.load(ident, base=tmp_path) == ("Evren\nCEO", "<b>Evren</b>", [])


def test_load_without_configured_files_is_no_signature():
    assert signature.load(Identity("k@p.me")) == (None, None, [])


def test_load_missing_file_is_a_hard_error(tmp_path):
    """Silently sending without the signature the user configured is the worse failure."""
    ident = Identity("k@p.me", signature_file="gone.sig")
    with pytest.raises(BridgeError) as excinfo:
        signature.load(ident, base=tmp_path)
    assert "gone.sig" in excinfo.value.detail


def test_load_expands_the_home_shortcut(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # expanduser() reads this on Windows
    (tmp_path / "k.sig").write_text("Evren", encoding="utf-8")
    ident = Identity("k@p.me", signature_file="~/k.sig")
    assert signature.load(ident, base=tmp_path / "elsewhere")[0] == "Evren"


def test_load_picks_up_the_image_the_signature_references(tmp_path):
    """The cid is the file name — that is the whole link between config and logo."""
    (tmp_path / "k.html").write_text('<img src="cid:k.sig.0.png">', encoding="utf-8")
    (tmp_path / "k.sig.0.png").write_bytes(b"\x89PNG")
    ident = Identity("k@p.me", signature_html_file="k.html")
    assert signature.load(ident, base=tmp_path)[2] == [("k.sig.0.png", b"\x89PNG", "image/png")]


def test_a_dangling_image_reference_is_a_hard_error(tmp_path):
    """Sending a signature whose logo renders as a hole is the bug this guards."""
    (tmp_path / "k.html").write_text('<img src="cid:580bd272@yell.services">', encoding="utf-8")
    ident = Identity("k@p.me", signature_html_file="k.html")
    with pytest.raises(BridgeError) as excinfo:
        signature.load(ident, base=tmp_path)
    assert "580bd272@yell.services" in excinfo.value.detail


def test_an_image_reference_never_escapes_the_signature_directory(tmp_path):
    (tmp_path / "k.html").write_text('<img src="cid:../../etc/passwd">', encoding="utf-8")
    ident = Identity("k@p.me", signature_html_file="k.html")
    with pytest.raises(BridgeError):
        signature.load(ident, base=tmp_path)


def test_embed_rewrites_protons_cids_to_local_files():
    html = '<img src="cid:580bd272@yell.services"><img src="cid:580bd272@yell.services">'
    parts = {"580bd272@yell.services": (b"\x89PNG", "logo.png", "image/png")}
    out, files = signature.embed(html, parts, "kontakt")
    assert out == '<img src="cid:kontakt.sig.0.png"><img src="cid:kontakt.sig.0.png">'
    assert files == {"kontakt.sig.0.png": b"\x89PNG"}


def test_embed_leaves_a_reference_the_message_does_not_carry():
    html = '<img src="cid:foreign@x.de"><img src="https://x.de/logo.png">'
    assert signature.embed(html, {}, "kontakt") == (html, {})


# --- extracting from a sent message ---------------------------------------------


def test_extract_takes_the_user_block_without_the_proton_footer():
    text, html = signature.extract(PROTON_HTML)
    assert "Evren Tiras" in html
    assert "Proton Mail" not in html
    assert text == "Evren Tiras\nGeschäftsführer & Co."   # entities resolved for the text part


def test_extract_falls_back_to_the_whole_block(monkeypatch):
    html_without_user_div = (
        '<div class="protonmail_signature_block">Evren Tiras<br>CEO</div>'
    )
    text, html = signature.extract(html_without_user_div)
    assert html == "Evren Tiras<br>CEO"
    assert text == "Evren Tiras\nCEO"


def test_a_quoted_foreign_signature_is_never_mistaken_for_our_own():
    """Cutting the text part at the last `-- ` was tried against a real mailbox and returned
    the footer of a supplier's quoted mail. Only Proton's own marker counts."""
    quoted = (
        "<div>Hallo, anbei die Rechnung.</div>"
        "<blockquote>Mit freundlichen Grüßen<br>-- <br>"
        "Heike Schmidt<br>KÄRCHER Center Seßler GmbH</blockquote>"
    )
    assert signature.extract(quoted) == (None, None)


def test_an_empty_block_means_the_address_has_no_signature():
    """Proton writes `…_block-empty` when nothing is configured — that is an answer."""
    assert signature.extract(EMPTY_BLOCK) == (None, None)


def test_an_empty_user_block_never_falls_back_to_the_proton_footer():
    only_footer = (
        '<div class="protonmail_signature_block">'
        '<div class="protonmail_signature_block-user protonmail_signature_block-empty">'
        "</div>"
        '<div class="protonmail_signature_block-proton">'
        'Sent with <a href="https://proton.me/">Proton Mail</a> secure email.</div></div>'
    )
    assert signature.extract(only_footer) == (None, None)


def test_an_image_only_signature_counts():
    block = ('<div class="protonmail_signature_block-user">'
             '<img src="cid:logo@p.me" alt=""></div>')
    text, html = signature.extract(block)
    assert text is None
    assert "<img" in html


def test_extract_finds_nothing_rather_than_guessing():
    assert signature.extract("<p>Hallo, bis morgen.</p>") == (None, None)


# --- the send path ---------------------------------------------------------------


def _patch(monkeypatch, sent, tmp_path, with_logo=False):
    (tmp_path / "k.sig").write_text("Evren\nCEO", encoding="utf-8")
    html_file = None
    if with_logo:
        (tmp_path / "k.sig.html").write_text('Evren<img src="cid:k.sig.0.png">', encoding="utf-8")
        (tmp_path / "k.sig.0.png").write_bytes(b"\x89PNG")
        html_file = str(tmp_path / "k.sig.html")
    config = Config(
        Endpoint(),
        [Account("me@p.me", "pw", identities=[
            Identity("kontakt@p.me", name="Kontakt", label="kontakt",
                     signature_file=str(tmp_path / "k.sig"),
                     signature_html_file=html_file),
        ])],
        "me@p.me",
    )
    monkeypatch.setattr(cfgmod, "resolve_config", lambda *a, **k: config)

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def send(self, msg):
            sent.append(msg)
            return msg["Message-ID"]

    monkeypatch.setattr(
        SmtpSession, "connect", classmethod(lambda cls, ep, acc, **k: FakeSession())
    )


def test_send_appends_the_identity_signature(monkeypatch, tmp_path):
    sent = []
    _patch(monkeypatch, sent, tmp_path)
    result = CliRunner().invoke(main, ["compose", "send", "--to", "a@x.de", "--subject", "S",
                                       "--body", "B", "--identity", "kontakt", "--yes"])
    assert result.exit_code == 0
    assert sent[0].get_content() == "B\n\n-- \nEvren\nCEO\n"


def test_no_signature_suppresses_it(monkeypatch, tmp_path):
    sent = []
    _patch(monkeypatch, sent, tmp_path)
    result = CliRunner().invoke(main, ["compose", "send", "--to", "a@x.de", "--subject", "S",
                                       "--body", "B", "--identity", "kontakt",
                                       "--no-signature", "--yes"])
    assert result.exit_code == 0
    assert sent[0].get_content() == "B\n"


def test_identity_without_a_signature_sends_the_bare_body(monkeypatch, tmp_path):
    sent = []
    _patch(monkeypatch, sent, tmp_path)
    result = CliRunner().invoke(main, ["compose", "send", "--to", "a@x.de", "--subject", "S",
                                       "--body", "B", "--yes"])   # login address, no signature
    assert result.exit_code == 0
    assert sent[0].get_content() == "B\n"


def test_dry_run_names_the_signature_file(monkeypatch, tmp_path):
    sent = []
    _patch(monkeypatch, sent, tmp_path)
    result = CliRunner().invoke(main, ["--json", "compose", "send", "--to", "a@x.de",
                                       "--subject", "S", "--body", "B",
                                       "--identity", "kontakt", "--dry-run"])
    assert result.exit_code == 0
    assert sent == []
    assert json.loads(result.output)["signature"] == str(tmp_path / "k.sig")


def test_reply_signs_with_the_answering_identity(monkeypatch, tmp_path):
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    sent = []
    _patch(monkeypatch, sent, tmp_path)
    msg = FakeMessage(to=("kontakt@p.me",))
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox({"INBOX": [msg]}), acc.email)),
    )
    result = CliRunner().invoke(main, ["compose", "reply", "--uid", "1", "--body", "ok", "--yes"])
    assert result.exit_code == 0
    assert sent[0].get_content() == "ok\n\n-- \nEvren\nCEO\n"


def test_forward_carries_the_logo_above_the_quoted_mail(monkeypatch, tmp_path):
    """`forward` assembles its own body, so it used to miss the HTML signature entirely —
    the logo has to sit under the forwarder's own words, not under the quoted message."""
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox
    sent = []
    _patch(monkeypatch, sent, tmp_path, with_logo=True)
    monkeypatch.setattr(
        ImapClient, "connect",
        classmethod(lambda cls, ep, acc, **k: ImapClient(FakeMailBox(), acc.email)),
    )
    result = CliRunner().invoke(main, ["compose", "forward", "--uid", "1", "--to", "x@y.de",
                                       "--body", "FYI", "--identity", "kontakt", "--yes"])
    assert result.exit_code == 0
    html = sent[0].get_body(preferencelist=("html",)).get_content()
    assert html.index('<img src="cid:k.sig.0.png">') < html.index("Forwarded message")
    assert "<k.sig.0.png>" in [p.get("Content-ID") for p in sent[0].walk()]


def test_draft_carries_the_signature(monkeypatch, tmp_path):
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox
    sent = []
    _patch(monkeypatch, sent, tmp_path)
    mb = FakeMailBox()
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(mb, acc.email))
    )
    result = CliRunner().invoke(main, ["compose", "draft", "--to", "a@x.de", "--subject", "S",
                                       "--body", "B", "--identity", "kontakt"])
    assert result.exit_code == 0
    assert b"-- \nEvren\nCEO" in mb.appended[0][2]


# --- importing from a sent message ------------------------------------------------


def _import_setup(monkeypatch, tmp_path, identities, html=PROTON_HTML, text="Hallo.",
                  older=()):
    """A config file at a known path plus a Sent folder, newest message last."""
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage

    path = tmp_path / "config.toml"
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    cfgmod.save_config(
        Config(Endpoint(), [Account("me@p.me", "pw", identities=identities)], "me@p.me"), path
    )
    msgs = [
        FakeMessage(uid=str(i + 1), from_="kontakt@p.me", html=h, text=t, attachments=[])
        for i, (h, t) in enumerate([*older, (html, text)])
    ]
    box = FakeMailBox({"Sent": msgs}, folder_flags={"Sent": ("\\Sent",)})
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(box, acc.email))
    )
    return path


def test_import_previews_and_changes_nothing_without_save(monkeypatch, tmp_path):
    path = _import_setup(monkeypatch, tmp_path,
                         [Identity("kontakt@p.me", label="kontakt")])
    before = path.read_text(encoding="utf-8")
    result = CliRunner().invoke(main, ["--json", "account", "identity", "signature", "import",
                                       "--identity", "kontakt"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["signature"] == "Evren Tiras\nGeschäftsführer & Co."
    assert "Proton Mail" not in data["signature_html"]
    assert data["saved"] is None
    assert path.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.sig"))


def test_import_writes_the_files_and_links_them_relatively(monkeypatch, tmp_path):
    path = _import_setup(monkeypatch, tmp_path,
                         [Identity("kontakt@p.me", label="kontakt")])
    result = CliRunner().invoke(main, ["--json", "account", "identity", "signature", "import",
                                       "--identity", "kontakt", "--save"])
    assert result.exit_code == 0
    assert (tmp_path / "kontakt.sig").read_text(encoding="utf-8").startswith("Evren Tiras")
    assert "Evren Tiras" in (tmp_path / "kontakt.sig.html").read_text(encoding="utf-8")
    ident = cfgmod.load_config(path).accounts[0].identities[0]
    assert ident.signature_file == "kontakt.sig"          # portable next to config.toml
    assert ident.signature_html_file == "kontakt.sig.html"


def test_import_stores_an_absolute_path_outside_the_config_dir(monkeypatch, tmp_path):
    path = _import_setup(monkeypatch, tmp_path, [Identity("kontakt@p.me", label="kontakt")])
    elsewhere = tmp_path / "sigs"
    result = CliRunner().invoke(main, ["account", "identity", "signature", "import",
                                       "--identity", "kontakt", "--dir", str(elsewhere),
                                       "--save"])
    assert result.exit_code == 0
    ident = cfgmod.load_config(path).accounts[0].identities[0]
    assert ident.signature_file == str(elsewhere / "kontakt.sig")


def test_import_gives_the_login_address_an_entry_of_its_own(monkeypatch, tmp_path):
    """The login address is an implicit identity — without an entry the paths have no home."""
    path = _import_setup(monkeypatch, tmp_path, [])
    result = CliRunner().invoke(main, ["account", "identity", "signature", "import", "--save"])
    assert result.exit_code == 0
    identities = cfgmod.load_config(path).accounts[0].identities
    assert [i.email for i in identities] == ["me@p.me"]
    assert identities[0].signature_file == "me.sig"


def test_import_refuses_to_guess_without_a_marker(monkeypatch, tmp_path):
    path = _import_setup(monkeypatch, tmp_path, [Identity("kontakt@p.me", label="kontakt")],
                         html="<p>Hallo.</p>", text="Hallo.")
    before = path.read_text(encoding="utf-8")
    result = CliRunner().invoke(main, ["--json", "account", "identity", "signature", "import",
                                       "--identity", "kontakt", "--save"])
    assert result.exit_code != 0
    assert json.loads(result.output)["error"]["title"] == "No signature found"
    assert path.read_text(encoding="utf-8") == before


def test_import_reads_back_past_the_mails_this_cli_sent(monkeypatch, tmp_path):
    """The newest sent mail is normally one this CLI sent — and carries no block at all."""
    _import_setup(monkeypatch, tmp_path, [Identity("kontakt@p.me", label="kontakt")],
                  html=None, text="Sent via the CLI.", older=[(PROTON_HTML, "Hallo.")])
    result = CliRunner().invoke(main, ["--json", "account", "identity", "signature", "import",
                                       "--identity", "kontakt", "--save"])
    assert result.exit_code == 0
    assert json.loads(result.output)["source_uid"] == "1"   # the older, signed message
    assert (tmp_path / "kontakt.sig").read_text(encoding="utf-8").startswith("Evren Tiras")


def test_import_never_saves_an_empty_proton_signature(monkeypatch, tmp_path):
    _import_setup(monkeypatch, tmp_path, [Identity("kontakt@p.me", label="kontakt")],
                  html=EMPTY_BLOCK, text="Hallo.")
    result = CliRunner().invoke(main, ["--json", "account", "identity", "signature", "import",
                                       "--identity", "kontakt", "--save"])
    assert result.exit_code != 0
    assert json.loads(result.output)["error"]["title"] == "No signature found"
    assert not list(tmp_path.glob("*.sig*"))


def test_import_confirms_before_overwriting(monkeypatch, tmp_path):
    _import_setup(monkeypatch, tmp_path, [Identity("kontakt@p.me", label="kontakt")])
    (tmp_path / "kontakt.sig").write_text("handwritten", encoding="utf-8")
    args = ["account", "identity", "signature", "import", "--identity", "kontakt", "--save"]
    result = CliRunner().invoke(main, args, input="n\n")
    assert result.exit_code != 0
    assert (tmp_path / "kontakt.sig").read_text(encoding="utf-8") == "handwritten"
    assert CliRunner().invoke(main, [*args, "--yes"]).exit_code == 0
    assert (tmp_path / "kontakt.sig").read_text(encoding="utf-8").startswith("Evren Tiras")


# --- config round-trip -----------------------------------------------------------


def test_signature_paths_survive_a_save_load_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    cfgmod.save_config(
        Config(Endpoint(), [Account("me@p.me", "pw", identities=[
            Identity("k@p.me", label="kontakt", signature_file="k.sig",
                     signature_html_file="k.html"),
        ])]),
        path,
    )
    loaded = cfgmod.load_config(path).accounts[0].identities[0]
    assert loaded.signature_file == "k.sig"
    assert loaded.signature_html_file == "k.html"
