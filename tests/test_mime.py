from __future__ import annotations

from proton_mail_bridge.utils import mime


def test_plain_message_headers():
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=["c@x.de"], bcc=None,
        subject="Hallo", body_text="Text", body_html=None, attachments=None,
    )
    assert msg["From"] == "me@p.me"
    assert msg["To"] == "a@x.de"
    assert msg["Cc"] == "c@x.de"
    assert msg["Subject"] == "Hallo"
    assert msg.get_content().strip() == "Text"


def test_html_alternative_and_reply_headers():
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="Re: X",
        body_text="t", body_html="<p>t</p>", attachments=None,
        in_reply_to="<id@x>", references=["<id@x>"],
    )
    assert msg["In-Reply-To"] == "<id@x>"
    assert msg.is_multipart()


def test_attachment_added(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hi")
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="b", body_html=None, attachments=[str(f)],
    )
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert "a.txt" in names


def test_attachment_from_bytes_tuple():
    msg = mime.build_message(
        sender="me@p.me", to=["a@x.de"], cc=None, bcc=None, subject="S",
        body_text="b", body_html=None, attachments=[("r.pdf", b"%PDF-1.4", "application/pdf")],
    )
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert "r.pdf" in names
