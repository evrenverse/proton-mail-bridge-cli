from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from proton_mail_bridge.utils import signature as sig_mod


def build_message(
    *,
    sender: str,
    to: list[str],
    cc: list[str] | None,
    bcc: list[str] | None,
    subject: str,
    body_text: str,
    body_html: str | None,
    attachments: list[str | tuple[str, bytes, str | None]] | None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    signature: str | None = None,
    signature_html: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        filtered = [r for r in references if r]
        if filtered:
            msg["References"] = " ".join(filtered)

    text = body_text or ""
    if signature:
        text = sig_mod.append_text(text, signature)
    msg.set_content(text)
    if body_html:
        # A signature-only HTML part would turn every plain send into multipart.
        if signature_html:
            body_html = sig_mod.append_html(body_html, signature_html)
        msg.add_alternative(body_html, subtype="html")

    for att in attachments or []:
        if isinstance(att, (tuple, list)):
            filename, data, ctype = att
        else:
            path = Path(att)
            data = path.read_bytes()
            filename = path.name
            ctype = None
        ctype = ctype or mimetypes.guess_type(filename)[0]
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg
