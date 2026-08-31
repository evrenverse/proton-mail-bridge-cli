"""Sender signatures.

The Bridge is a plain SMTP relay: it encrypts and forwards the MIME message the client
hands it and never adds the signature configured in the Proton apps — that one is only
inserted by Proton's own composers. So the signature lives in local files referenced
from the config, and `extract` can lift it out of a message Proton itself has sent.
"""

from __future__ import annotations

import mimetypes
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from proton_mail_bridge.core.config import Identity, resolve_path
from proton_mail_bridge.core.errors import BridgeError

SEPARATOR = "-- "  # RFC 3676 §4.3 signature delimiter
BLOCK = "protonmail_signature_block"
USER_BLOCK = f"{BLOCK}-user"  # excludes Proton's own "Sent with Proton Mail" footer
_BREAKS = ("br", "div", "p", "tr", "li")
_CID = re.compile(r"""src=(["'])cid:([^"']*)\1""", re.IGNORECASE)


def append_text(body: str, sig: str) -> str:
    prefix = f"{body.rstrip()}\n\n" if body.strip() else ""
    return f"{prefix}{SEPARATOR}\n{sig}"


def append_html(body_html: str, sig_html: str) -> str:
    return f"{body_html}\n<br>\n{sig_html}"


def load(
    ident: Identity, base: Path | None = None
) -> tuple[str | None, str | None, list[tuple[str, bytes, str]]]:
    """(text, html, images) signature of an identity; the files are read right here.

    `images` are the inline parts the HTML references by `cid:` — a logo only reaches the
    recipient when the message actually carries it.
    """
    html = _read(ident.signature_html_file, base)
    return _read(ident.signature_file, base), html, images(html, ident, base)


def images(
    html: str | None, ident: Identity, base: Path | None = None
) -> list[tuple[str, bytes, str]]:
    """(cid, data, content type) per `cid:` reference of the HTML signature.

    The cid *is* the file name, and the files sit next to the HTML: `import --save`
    rewrites Proton's own ids to what it wrote, so the config needs no third path.
    """
    if not html or not ident.signature_html_file:
        return []
    folder = resolve_path(ident.signature_html_file, base).parent
    out: list[tuple[str, bytes, str]] = []
    for cid in dict.fromkeys(m.group(2) for m in _CID.finditer(html)):
        path = folder / cid
        if Path(cid).name != cid or not path.is_file():
            # A dangling cid is an invisible logo — the exact failure this file exists for.
            raise BridgeError(
                "config",
                "Signature image missing",
                f"{ident.signature_html_file} references cid:{cid}, but no such file sits "
                f"in {folder}. Re-run `account identity signature import --save` to write "
                "the images, or send with --no-signature.",
            )
        ctype = mimetypes.guess_type(cid)[0] or "application/octet-stream"
        out.append((cid, path.read_bytes(), ctype))
    return out


def embed(
    sig_html: str, parts: dict[str, tuple[bytes, str | None, str | None]], stem: str
) -> tuple[str, dict[str, bytes]]:
    """Repoint the signature at local copies: (rewritten HTML, {file name: bytes}).

    `parts` maps the source message's Content-IDs to (payload, filename, content type).
    A reference the message does not carry — a remote URL, an already-local name — is
    left alone.
    """
    files: dict[str, bytes] = {}
    names: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        cid = match.group(2)
        part = parts.get(cid)
        if not part:
            return match.group(0)
        if cid not in names:
            data, filename, ctype = part
            ext = Path(filename or "").suffix or mimetypes.guess_extension(ctype or "") or ".png"
            names[cid] = f"{stem}.sig.{len(names)}{ext}"
            files[names[cid]] = data
        return f'src="cid:{names[cid]}"'

    return _CID.sub(repl, sig_html), files


def _read(value: str | None, base: Path | None) -> str | None:
    if not value:
        return None
    try:
        return resolve_path(value, base).read_text(encoding="utf-8").strip("\n")
    except OSError as exc:
        # Sending without the signature the user configured is worse than not sending.
        raise BridgeError(
            "config", "Signature file unreadable", f"{value}: {exc.strerror or exc}"
        ) from exc


def extract(body_html: str | None) -> tuple[str | None, str | None]:
    """Signature of a message Proton sent: (text, html), each None when not found.

    Only Proton's own `protonmail_signature_block` counts, and the text is rendered from
    it. Cutting the plain-text part at an RFC 3676 `-- ` separator was tried and dropped:
    the last such separator in a real mail usually belongs to a *quoted* signature, so it
    happily returned some other company's footer as the user's own.

    A block that is present but carries nothing visible is Proton stating that this
    address has no signature (it marks those `…_block-empty`). That is an answer, not a
    miss: falling through would hand back the "Sent with Proton Mail" footer instead.
    """
    for marker in (USER_BLOCK, BLOCK):
        parser = _Block(marker)
        parser.feed(body_html or "")
        parser.close()
        if not parser.found:
            continue
        html = "".join(parser.html).strip()
        text = _tidy("".join(parser.text))
        if text or "<img" in html.lower():  # an image-only signature has no text
            return text or None, html
        return None, None
    return None, None


def _tidy(text: str) -> str:
    return "\n".join(line for line in (x.strip() for x in text.splitlines()) if line)


class _Block(HTMLParser):
    """Collects one element by class name — inner markup intact, plus a text rendering.

    Nesting is tracked by counting the block's own tag name, so a signature made of
    nested divs is closed at the right place.
    """

    def __init__(self, wanted: str):
        super().__init__(convert_charrefs=False)
        self._wanted = wanted
        self._tag: str | None = None
        self._depth = 0
        self.found = False  # the block existed, even if it turned out to be empty
        self.html: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if not self._depth:
            if self._wanted in (dict(attrs).get("class") or "").split():
                self._tag, self._depth = tag, 1
                self.found = True
            return  # the wrapper itself is not part of the signature
        if tag == self._tag:
            self._depth += 1
        self.html.append(self.get_starttag_text() or f"<{tag}>")
        if tag in _BREAKS:
            self.text.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # Self-closing: no end tag follows, so it must not change the depth.
        if not self._depth:
            return
        self.html.append(self.get_starttag_text() or f"<{tag}/>")
        if tag in _BREAKS:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag == self._tag:
            self._depth -= 1
            if not self._depth:
                return  # closes the block itself
        self.html.append(f"</{tag}>")
        if tag in _BREAKS:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.html.append(data)
            self.text.append(data)

    def handle_entityref(self, name: str) -> None:
        self._charref(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._charref(f"&#{name};")

    def _charref(self, raw: str) -> None:
        if self._depth:
            self.html.append(raw)  # the HTML part keeps the entity as Proton wrote it
            self.text.append(unescape(raw))
