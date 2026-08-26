"""One-time verification codes, pulled out of a message.

The regex is the easy half. The hard half is everything that looks like a code and is not,
and every rule below was written against real mail rather than guessed:

- `Gültig bis: 26.08.2026 18:55` -- voelkner prints the expiry right under the code
- `Klaus-Conrad-Str. 1 92242 Hirschau` -- a house number and a postal code, side by side
- `Reg. code 14532901`, `HRB 13665`, `USt ID: DE184048859` -- the imprint
- `#3944`, `#1330` -- pull request numbers in GitHub release notes, anchored on "Decode"
- `87.191.52.218`, `15:46:31`, `© 2026` -- Indeed's own login report
- `LinkId=521839` -- a tracking id inside a URL
- `10% Rabatt … Code: LASI10` -- a discount code, which is a code but not this kind

Three rules do the filtering, and all three matter more than the pattern:

1. A candidate only counts when a code word stands next to it. Unanchored digits do not
   exist for this module -- that alone removes the imprint, the address block and the
   footer, which is where nearly all the tempting numbers live.
2. A code printed in groups must come out in *equal* groups. `582 800` is a code,
   `2026 18` is a year meeting an hour.
3. Digits win. A candidate with letters in it is considered only when no digit candidate
   qualified, because o2 prints `DIESEN CODE BITTE NIEMALS AM TELEFON VORLESEN` right next
   to its code and every word in that sentence has the shape of a letter code.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import re

WINDOW_BEFORE = 60
"""Characters to look back from a code word. METRO puts the code in front of it:
`541960 - Dein METRO Verifizierungs-Code`."""

WINDOW_AFTER = 140
"""Characters to look ahead. Wider than it looks necessary: senders put boilerplate
between the label and the value. Kinde writes `This code will expire in 2 hours. If you
don't think you should be receiving this email, you can safely ignore it.` and only then
the code -- 105 characters, which a window of 100 misses by five.

Measured against 1495 real messages: 100 misses Kinde, 140 catches it for two extra false
positives, and 200 buys no further recall while costing two more."""

_KEYWORD = re.compile(
    r"""
      \w*codes?\b                                   # code, Verifizierungscode, Sicherheitscode
    | one[-\s]?time[-\s]?(?:password|passcode|pin|passwort|kennwort)
    | einmal[-\s]?(?:pin|passwort|kennwort)
    | \bpasscode\b | \botp\b | \btan\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Words that end in "code" but never introduce one. Without this, GitHub release notes
# anchor on "Decode"/"Encode" and hand back pull request numbers, a job digest anchors on
# "Low-Code", and every shop footer anchors on "Rabattcode". Tested against the keyword
# plus the few characters in front of it, so spaced and hyphenated forms are caught too.
_NOT_AN_ANCHOR = re.compile(
    r"(?:de|en|uni|bar|geo|post|zip|op|short|low|no|hs|qr|vs|source|country|area|dial|"
    r"reg\.?|registration|promo|rabatt|gutschein|aktions|vorteils|coupon|schad|quell|"
    r"fehler|status|zeichen|farb|länder|landes|sprach|dress|strich|morse|binär)"
    r"[\s.-]?codes?\s*$",
    re.IGNORECASE,
)

ANCHOR_PREFIX = 14
"""Characters read in front of a code word to recognize a blocked one. Long enough for
`registration code`, short enough not to reach back into the previous sentence."""

# A solid run of 4-8 digits. `#` sits among the boundary characters: `#3944` is a pull
# request, never a code, and GitHub notification mail is full of them.
_DIGITS_SOLID = re.compile(r"(?<![\w#§+-])\d{4,8}(?![\w-])")

# The same, printed in groups. Group sizes are compared in _grouped(), not here.
_DIGITS_GROUPED = re.compile(r"(?<![\w#§+-])\d{1,4}(?:[   -]\d{1,4}){1,5}(?![\w-])")
_GROUP_SEP = re.compile(r"[   -]")

# 4-8 uppercase characters with at least one letter AND at least one digit. Requiring the
# digit is what separates a code from a word: without it this tier returns HTTP, CLAUDE,
# SELLWERK and every shouted button label a newsletter contains.
# ponytail: costs pure-letter codes (Discord sends BSDTKC); a missing code is a clean
# error, a wrong one gets typed into a login form. Revisit only with a better separator.
_ALNUM = re.compile(r"(?<![\w#§+-])(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{4,8}(?![\w-])")

_URLS = re.compile(r"https?://\S+|\bwww\.\S+|[\w.+-]+@[\w-]+\.[\w.-]+")
_INVISIBLE = re.compile("[­͏​-‍⁠﻿]")
_TAGS = re.compile(r"(?s)<[^>]+>")
_DROPPED_ELEMENTS = re.compile(r"(?is)<(script|style|head)\b.*?</\1>")
_COMMENTS = re.compile(r"(?s)<!--.*?-->")
_BREAKS = re.compile(r"(?is)<(?:br|/p|/div|/tr|/td|/h[1-6]|/li)\s*/?>")


def parse_window(value: str) -> _dt.timedelta:
    """`10m`, `2h`, `1d` -- a bare number means minutes. Codes expire in minutes, so this
    takes a duration where the rest of the CLI's `--since` takes an ISO date."""
    match = re.fullmatch(r"\s*(\d+)\s*([mhd]?)\s*", value or "", re.IGNORECASE)
    if not match:
        raise ValueError(f"not a duration: {value!r} (expected e.g. 10m, 2h, 1d)")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"duration must be positive: {value!r}")
    unit = match.group(2).lower() or "m"
    return _dt.timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: amount})


def to_text(html: str) -> str:
    """HTML to plain text. Drops `<style>`/`<script>`/`<head>` *with their content* first:
    a stylesheet is full of 3-6 digit numbers, and stripping tags alone spills all of them
    into the text. Most of these messages have no text/plain part at all, so this is the
    normal path, not a fallback."""
    if not html:
        return ""
    text = _DROPPED_ELEMENTS.sub(" ", html)
    text = _COMMENTS.sub(" ", text)
    text = _BREAKS.sub("\n", text)
    text = _TAGS.sub(" ", text)
    return _html.unescape(text)


def _flatten(subject: str | None, body_text: str | None, body_html: str | None) -> str:
    """Subject and body as one flat string. The subject is searched too: LinkedIn, METRO,
    Indeed and OpenAI put the code there, and no place is easier to read it from."""
    body = (body_text or "").strip() or to_text(body_html or "")
    text = f"{subject or ''}\n{body}"
    text = _INVISIBLE.sub("", text)  # senders pad codes with soft hyphens
    text = _URLS.sub(" ", text)  # tracking ids look exactly like codes
    return re.sub(r"\s+", " ", text)


def _windows(text: str) -> list[tuple[int, int]]:
    """One search window per code word, minus the words that only look like one."""
    windows = []
    for match in _KEYWORD.finditer(text):
        lead = text[max(0, match.start() - ANCHOR_PREFIX):match.end()]
        if _NOT_AN_ANCHOR.search(lead):
            continue
        windows.append((max(0, match.start() - WINDOW_BEFORE), match.end() + WINDOW_AFTER))
    return windows


def _anchored(text: str, pattern: re.Pattern[str], windows: list[tuple[int, int]]) -> list[str]:
    return [
        m.group(0)
        for m in pattern.finditer(text)
        if any(start <= m.start() and m.end() <= end for start, end in windows)
    ]


def _is_year(code: str) -> bool:
    """A four-digit year is the most common false positive of them all -- every footer has
    one. A real code of 2026 is thrown away with it; that costs a clean "no code found" and
    saves typing a copyright notice into a login form."""
    return len(code) == 4 and 1900 <= int(code) <= 2100


def _grouped(token: str) -> str | None:
    """A grouped candidate, joined -- or None when the groups are uneven and it is
    therefore two numbers that happen to stand next to each other."""
    parts = _GROUP_SEP.split(token)
    if len({len(p) for p in parts}) != 1:
        return None
    joined = "".join(parts)
    return joined if 4 <= len(joined) <= 8 else None


def extract(subject: str | None, body_text: str | None, body_html: str | None) -> list[str]:
    """Distinct code candidates of one message, in order of appearance.

    More than one means the message cannot be used: nothing in it says which of them the
    form wants, and taking the first would be a guess. This function does not choose --
    the caller decides what an ambiguous message is worth.
    """
    text = _flatten(subject, body_text, body_html)
    windows = _windows(text)
    if not windows:
        return []

    digits = _anchored(text, _DIGITS_SOLID, windows)
    digits += [g for t in _anchored(text, _DIGITS_GROUPED, windows) if (g := _grouped(t))]
    candidates = [c for c in digits if not _is_year(c)]
    if not candidates:
        candidates = _anchored(text, _ALNUM, windows)

    return list(dict.fromkeys(candidates))


def parse_date(value: str | None) -> _dt.datetime | None:
    """A record's `date` as an aware datetime, or None when it cannot be read.

    This is the sender's `Date` header -- the same field the rest of the CLI sorts by.
    Freshness is part of correctness for a code, so a message whose timestamp cannot be
    read is skipped rather than assumed recent.
    """
    try:
        when = _dt.datetime.fromisoformat(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=_dt.UTC)


def shape(code: str) -> str:
    """How a candidate looks, for an error message that must not quote it."""
    return f"{len(code)} digits" if code.isdigit() else f"{len(code)} characters"
