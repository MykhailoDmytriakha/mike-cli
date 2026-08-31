"""Stamp — the fingerprint line at the end of README.md, TODO.md, JOURNAL.md (rules S1–S4, F0).

The stamp is the last line of the file: `stamp: <first 12 hex chars of sha256>` computed over
everything above that line. No copies, no side files. Only `mike` writes it.
"""
import hashlib
import re

STAMP_RE = re.compile(r"^stamp: ([0-9a-f]{12})$")
STAMP_LEN = 12


def split(text: str):
    """Return (body, stamp_or_None). `body` is the text without the stamp line.

    The stamp is recognised only as the LAST non-empty line (S1): anything written after it
    means the stamp is not last, so it is reported as absent and the whole text is the body.
    """
    lines = text.rstrip("\n").split("\n") if text.strip() else []
    if lines:
        m = STAMP_RE.match(lines[-1])
        if m:
            body_lines = lines[:-1]
            while body_lines and body_lines[-1] == "":  # tolerate the blank line before the stamp
                body_lines.pop()
            body = "\n".join(body_lines)
            return (body + "\n" if body else ""), m.group(1)
    return text, None


def compute(body: str) -> str:
    """sha256 of the body (normalised to end with exactly one newline), first 12 hex chars."""
    normalised = body.rstrip("\n") + "\n" if body.strip() else ""
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:STAMP_LEN]


def apply(body: str) -> str:
    """Return body with a fresh stamp line appended after one blank line (replacing an existing stamp)."""
    inner, _ = split(body)
    inner = inner.rstrip("\n") + "\n" if inner.strip() else ""
    return f"{inner}\nstamp: {compute(inner)}\n"


def verify(text: str):
    """Return (ok, reason). ok is True when the last line is a stamp matching the body.

    reason ∈ {"ok", "missing", "not-last", "mismatch"}.
    """
    body, found = split(text)
    if found is None:
        # A stamp line somewhere but not last → "not-last"; none at all → "missing".
        return (False, "not-last") if re.search(r"^stamp: [0-9a-f]{12}$", text, re.M) else (False, "missing")
    return (True, "ok") if compute(body) == found else (False, "mismatch")
