"""The TikTok UI profile (Q-50, PO 2026-10-16): TikTok's words, ids, waits and retries as data.

Admins edit it on the Admin page (every save is a new version with a reason, audited); Agents 0.7.0+
fetch the latest at /v1/agent/ui-profile and validate it again before use. SPEC, DEFAULTS and validate()
are a copy of agent/ui_profile.py (the server image has no Agent code); tests/unit/test_ui_profile.py
checks they are identical. What keeps a post safe stays in the Agent's code and cannot be set here.
"""

from __future__ import annotations

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
