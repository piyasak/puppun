"""Thai-safe line wrapping for burned-in text (FR-07, G3-03).

libass only wraps at spaces and Thai is written without spaces between words, so
long Thai lines would run off a 1080px frame. Lines are wrapped here instead, and
never split a base character from its combining vowel/tone marks or a leading
vowel (เ แ โ ใ ไ) from the consonant that follows it.
"""

from __future__ import annotations

import unicodedata

LEADING_VOWELS = set("เแโใไ")


def clusters(text: str) -> list[str]:
    """Split into display clusters: a base character plus its combining marks."""
    out: list[str] = []
    for ch in text:
        if out and (unicodedata.combining(ch) or unicodedata.category(ch) == "Mn"):
            out[-1] += ch
        elif out and out[-1] and out[-1][-1] in LEADING_VOWELS and len(out[-1]) == 1:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def display_width(text: str) -> int:
    return len(clusters(text))


def wrap(text: str, max_width: int, max_lines: int | None = None) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if display_width(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        parts = clusters(word)
        # Split an unspaced run into evenly sized lines so no line is left with an
        # orphaned character or two (e.g. a lone "ง").
        if len(parts) > max_width:
            pieces = -(-len(parts) // max_width)
            size = -(-len(parts) // pieces)
            while len(parts) > size:
                lines.append("".join(parts[:size]))
                parts = parts[size:]
        current = "".join(parts)
    if current:
        lines.append(current)
    if max_lines is not None and len(lines) > max_lines:
        last = clusters(lines[max_lines - 1])
        lines = lines[: max_lines - 1] + ["".join(last[: max_width - 1]) + "…"]
    return lines
