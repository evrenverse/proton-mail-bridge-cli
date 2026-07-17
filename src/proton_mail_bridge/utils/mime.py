from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path


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

    msg.set_content(body_text or "")
    if body_html:
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
