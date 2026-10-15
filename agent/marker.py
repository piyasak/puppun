"""The attempt marker in a caption: proof that a post on the phone is this attempt (PRD §H, Q-21).

Q-49 (PO 2026-10-15): no visible marker. "cf" + six hex digits put numbers in every caption, which the
PO says goes against TikTok's rules, so the same six hex digits (24 bits) are written with invisible
characters at the end of the caption: a word joiner, then one zero-width character per bit, then a word
joiner. Nothing shows on screen; the screen reader still sees the characters, and the caption check
compares them like any other text.

Whether TikTok keeps these characters in a posted caption is checked on a real phone before release
(docs/progress.md); a post whose marker cannot be found becomes UNKNOWN, never a guess.
"""

from __future__ import annotations

EDGE = "⁠"  # WORD JOINER
ZERO, ONE = "​", "‌"  # ZERO WIDTH SPACE, ZERO WIDTH NON-JOINER
BITS = 24


def code(post_id: str) -> str:
    """The six hex digits that identify the attempt (as the old visible "cf" marker did)."""
    return post_id.replace("-", "")[:6].lower()


def hidden(post_id: str) -> str:
    value = int(code(post_id), 16)
    return EDGE + "".join(ONE if value >> (BITS - 1 - i) & 1 else ZERO for i in range(BITS)) + EDGE


def found(text: str, post_id: str) -> bool:
    """True when `text` carries this attempt's hidden marker."""
    return hidden(post_id) in (text or "")


def visible(text: str) -> str:
    """The caption without invisible characters, for logs and messages."""
    return "".join(ch for ch in (text or "") if ch not in (EDGE, ZERO, ONE))
