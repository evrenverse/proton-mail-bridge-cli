from __future__ import annotations

# A page cap, not a size cap: text extraction cost scales with pages, and a search
# term that only appears on page 200 of a contract is not what --attachment-text is for.
MAX_PAGES = 50

# Where the extracted text rides on a record while the predicate runs. Leading
# underscore: it is scratch space, and search() strips it before anything is printed —
# a whole PDF per message would drown the output.
FIELD = "_attachment_text"


def extract(data: bytes) -> str:
    """Text of a PDF, empty string for anything unreadable.

    Scanned documents (an image per page) carry no text layer, so they come back
    empty — there is no OCR here. A caller reporting "not found" has to say so.
    """
    if not data[:5].startswith(b"%PDF"):
        return ""
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            try:  # empty user password is the common case for "protected" invoices
                reader.decrypt("")
            except Exception:
                return ""
        return "\n".join(p.extract_text() or "" for p in reader.pages[:MAX_PAGES])
    except Exception:
        # a broken or exotic PDF must not abort a search across a whole mailbox
        return ""
