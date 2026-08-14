"""PDF text extraction — the layer that lets --attachment-text see inside a receipt."""
from proton_mail_bridge.utils import pdftext, search


def _pdf(text: str) -> bytes:
    """A minimal one-page PDF printing `text`. Assembled by hand rather than with a
    writer library, so the test proves the reader works and nothing else."""
    stream = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET\n".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj" % i + body + b"endobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, xref)
    return bytes(out)


MINIMAL_PDF = _pdf("Rechnung 26593328")


def test_extract_reads_the_text_layer():
    assert "Rechnung 26593328" in pdftext.extract(MINIMAL_PDF)


def test_extract_survives_garbage():
    """A broken attachment must not abort a search across a whole mailbox."""
    assert pdftext.extract(b"") == ""
    assert pdftext.extract(b"not a pdf at all") == ""
    assert pdftext.extract(b"%PDF-1.4\ntruncated right here") == ""


def test_predicate_attachment_text():
    recs = [
        {"subject": "Fwd:", pdftext.FIELD: "Rechnung 26593328\nGesamtbetrag 683,24 EUR"},
        {"subject": "Foto", pdftext.FIELD: ""},
        {"subject": "Scan ohne Textebene"},  # no text layer → field absent
    ]
    keep = search.predicate(attachment_text="26593328")
    assert [r["subject"] for r in recs if keep(r)] == ["Fwd:"]
    assert search.predicate(attachment_text="GESAMTBETRAG")(recs[0]) is True
    assert search.predicate(attachment_text="x") is not None
