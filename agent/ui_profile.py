"""TikTok UI steps as data (Q-50, PO 2026-10-16): the "UI profile".

The words TikTok shows on its buttons, tabs, banners and menus, the id of a grid tile, and the waits and
retry counts change with TikTok versions; until 0.7.0 every such change needed a new Agent. The profile
carries them as data: an admin edits it on the Admin page (versioned, reason, audited), the server serves
the latest at /v1/agent/ui-profile, and the Agent fetches it on start and hourly, keeps the last good one
in its data folder and otherwise uses DEFAULTS below.

Only what is listed in SPEC can be set, with the limits there; anything else is refused whole (the last
good profile stays). What keeps a post safe stays in code and no profile can loosen it: the never-press
list (a profile may only add words), Post itself (its label and the single press under a grant), the
exact caption check, the attempt marker, and "unsure = UNKNOWN". A wrong profile can make the Agent stop
and wait for a person; it cannot make it post wrongly.

services/api/clipflow_api/ui_profile.py holds the same SPEC and DEFAULTS (the server image has no Agent
code); tests/unit/test_ui_profile.py checks that the two are identical.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# key -> ("labels", max items) | ("text", max length) | ("number", low, high)
SPEC: dict[str, tuple] = {
    "profile_tab": ("labels", 6),
    "following": ("labels", 6),
    "followers": ("labels", 6),
    "private_tab": ("labels", 6),
    "videos_tab": ("labels", 6),
    "videos_tab_icon": ("labels", 4),
    "share_video": ("labels", 6),
    "next_button": ("labels", 6),
    "close_button": ("labels", 6),
    "visibility_row": ("labels", 8),
    "only_me_words": ("labels", 8),
    "everyone_words": ("labels", 8),
    "only_me_option": ("labels", 6),
    "everyone_option": ("labels", 6),
    "resume_banner": ("labels", 6),
    "resume_cancel": ("labels", 4),
    "lock_desc": ("labels", 4),
    "private_caption_words": ("labels", 6),
    "pinned": ("labels", 6),
    "comments_button": ("labels", 6),
    "likes_label": ("labels", 4),
    "forbidden_exact_extra": ("labels", 30),
    "forbidden_fragments_extra": ("labels", 30),
    "login_markers_extra": ("labels", 30),
    "captcha_markers_extra": ("labels", 30),
    "grid_tile_id": ("text", 80),
    "settle_s": ("number", 0.5, 10),
    "wait_s": ("number", 5, 60),
    "account_tries": ("number", 2, 12),
    "verify_tries": ("number", 1, 8),
    "verify_wait_s": ("number", 5, 120),
    "public_tiles_to_scan": ("number", 1, 8),
}

DEFAULTS: dict[str, object] = {
    "profile_tab": ["โปรไฟล์", "Profile"],
    "following": ["กำลังติดตาม", "Following"],
    "followers": ["ผู้ติดตาม", "Followers"],
    "private_tab": ["วิดีโอส่วนตัว", "Private videos", "Private"],
    "videos_tab": ["วิดีโอ", "Videos"],
    "videos_tab_icon": ["โพสต์"],
    "share_video": ["วิดีโอ", "Video"],
    "next_button": ["ถัดไป", "Next"],
    "close_button": ["ปิด", "Close"],
    "visibility_row": ["ดูโพสต์นี้ได้", "can view this post", "can watch this"],
    "only_me_words": ["เฉพาะคุณ", "only you", "only me"],
    "everyone_words": ["ทุกคน", "everyone"],
    "only_me_option": ["เฉพาะคุณเท่านั้น", "Only you", "Only me"],
    "everyone_option": ["ทุกคน", "Everyone"],
    "resume_banner": ["แก้ไขวิดีโอที่ยังไม่ได้โพสต์ของคุณต่อหรือไม่"],
    "resume_cancel": ["ยกเลิก"],
    "lock_desc": ["ล็อก", "Private"],
    "private_caption_words": ["ส่วนตัว", "private"],
    "pinned": ["ปักหมุด", "Pinned"],
    "comments_button": ["อ่านหรือเพิ่มความคิดเห็น", "Read or add comments"],
    "likes_label": ["ถูกใจ", "Likes"],
    "forbidden_exact_extra": [],
    "forbidden_fragments_extra": [],
    "login_markers_extra": [],
    "captcha_markers_extra": [],
    "grid_tile_id": ":id/daw",
    "settle_s": 2.0,
    "wait_s": 15.0,
    "account_tries": 6,
    "verify_tries": 4,
    "verify_wait_s": 20.0,
    "public_tiles_to_scan": 4,
}

MAX_LABEL = 80


class ProfileError(ValueError):
    pass


def validate(body: object) -> dict:
    """The full profile (DEFAULTS with `body` on top), or ProfileError listing every problem."""
    if not isinstance(body, dict):
        raise ProfileError("the profile must be a JSON object")
    problems, out = [], dict(DEFAULTS)
    for key, value in body.items():
        rule = SPEC.get(key)
        if rule is None:
            problems.append(f"{key}: not a setting")
            continue
        kind = rule[0]
        if kind == "labels":
            if (not isinstance(value, list) or len(value) > rule[1]
                    or not all(isinstance(v, str) and 0 < len(v.strip()) <= MAX_LABEL for v in value)):
                problems.append(f"{key}: a list of at most {rule[1]} words of 1-{MAX_LABEL} characters")
                continue
            if not value and not key.endswith("_extra"):
                problems.append(f"{key}: at least one word")
                continue
            out[key] = [v.strip() for v in value]
        elif kind == "text":
            if not isinstance(value, str) or not 0 < len(value.strip()) <= rule[1]:
                problems.append(f"{key}: text of 1-{rule[1]} characters")
                continue
            out[key] = value.strip()
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not rule[1] <= value <= rule[2]:
                problems.append(f"{key}: a number from {rule[1]} to {rule[2]}")
                continue
            out[key] = value
    if problems:
        raise ProfileError("; ".join(problems))
    return out


@dataclass(frozen=True)
class UiProfile:
    version: int
    values: dict

    def __getattr__(self, key: str):
        try:
            return self.values[key]
        except KeyError:
            raise AttributeError(key) from None

    def labels(self, key: str) -> tuple[str, ...]:
        return tuple(self.values[key])


BUILT_IN = UiProfile(0, dict(DEFAULTS))


def from_server(answer: dict) -> UiProfile:
    """{"version": n, "body": {...}} from the server; ProfileError when it does not validate."""
    version = answer.get("version")
    if not isinstance(version, int) or version < 1:
        raise ProfileError("version: a positive whole number")
    return UiProfile(version, validate(answer.get("body")))


def cache_path(data_dir: Path) -> Path:
    return Path(data_dir) / "ui_profile.json"


def load_cached(data_dir: Path) -> UiProfile:
    """The last good profile kept on this PC, else the built-in one."""
    try:
        return from_server(json.loads(cache_path(data_dir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return BUILT_IN


def save_cached(data_dir: Path, answer: dict) -> None:
    path = cache_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(json.dumps({"version": answer["version"], "body": answer["body"]}, ensure_ascii=False),
                    encoding="utf-8")
    part.replace(path)
