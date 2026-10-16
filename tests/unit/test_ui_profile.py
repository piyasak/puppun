"""Q-50: TikTok's words, ids, waits and retries as an Admin-edited profile."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent import ui_profile
from agent.adb import Adb
from agent.tiktok_ui import TikTokUi, UiStop, forbidden, parse_dump

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))
from clipflow_api import ui_profile as server_rules  # noqa: E402


def test_server_and_agent_hold_the_same_rules_and_defaults():
    assert server_rules.SPEC == ui_profile.SPEC
    assert server_rules.DEFAULTS == ui_profile.DEFAULTS
    assert server_rules.validate({"settle_s": 3}) == ui_profile.validate({"settle_s": 3})


def test_the_defaults_are_a_valid_profile_and_only_listed_settings_with_limits_pass():
    assert ui_profile.validate({}) == ui_profile.DEFAULTS
    assert ui_profile.validate(dict(ui_profile.DEFAULTS)) == ui_profile.DEFAULTS
    good = ui_profile.validate({"profile_tab": ["Profil"], "verify_tries": 6})
    assert good["profile_tab"] == ["Profil"] and good["verify_tries"] == 6 and good["next_button"] == ["ถัดไป", "Next"]
    for bad in ({"post_button": ["x"]},  # Post is not a setting: it stays in code
                {"forbidden_exact": []},  # the never-press list cannot be replaced, only added to
                {"settle_s": 0}, {"verify_tries": 99}, {"profile_tab": []}, {"profile_tab": "Profile"},
                {"profile_tab": ["x" * 81]}, {"grid_tile_id": ""}, {"settle_s": True}, []):
        with pytest.raises(ui_profile.ProfileError):
            ui_profile.validate(bad)


def test_a_profile_can_only_add_never_press_words():
    profile = ui_profile.UiProfile(2, ui_profile.validate({"forbidden_fragments_extra": ["โปรโมต"]}))
    node = parse_dump('<hierarchy><node text="โปรโมตวิดีโอ" content-desc="" resource-id="" class="x" '
                      'clickable="true" bounds="[0,0][10,10]" /></hierarchy>')[0]
    assert forbidden(node, profile) and not forbidden(node)
    post = parse_dump('<hierarchy><node text="โพสต์" content-desc="" resource-id="" class="x" '
                      'clickable="true" bounds="[0,0][10,10]" /></hierarchy>')[0]
    assert forbidden(post, profile) and forbidden(post)  # Post stays never-pressed whatever the profile says


class Phone:
    def __init__(self, label):
        self.label, self.presses = label, []

    def run(self, args):
        cmd = args[3] if len(args) > 3 else ""
        if cmd.startswith("input swipe"):
            self.presses.append(cmd)
        if cmd.startswith("cat "):
            return ('<hierarchy><node text="" content-desc="' + self.label + '" resource-id="" '
                    'class="android.widget.FrameLayout" clickable="true" bounds="[576,1408][720,1506]" /></hierarchy>')
        if cmd.startswith("dumpsys window"):
            return "  mCurrentFocus=Window{1 u0 com.ss.android.ugc.trill/Fake}\n"
        return ""


def test_a_new_tiktok_word_works_from_the_profile_without_a_new_agent():
    phone = Phone("Profil")  # TikTok renamed its tab
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0)
    with pytest.raises(UiStop):
        ui.press(*ui.p.labels("profile_tab"))  # built-in words: not found
    profile = ui_profile.UiProfile(3, ui_profile.validate({"profile_tab": ["Profil"]}))
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, profile=profile)
    ui.press(*ui.p.labels("profile_tab"))
    assert phone.presses == ["input swipe 648 1457 648 1457 120"]


def test_waits_and_retries_come_from_the_profile_unless_given():
    profile = ui_profile.UiProfile(4, ui_profile.validate({"settle_s": 3.5, "wait_s": 30}))
    ui = TikTokUi(Adb(lambda a: ""), "S", profile=profile)
    assert (ui.settle_s, ui.wait_s) == (3.5, 30.0)
    assert TikTokUi(Adb(lambda a: ""), "S", settle_s=0, wait_s=0, profile=profile).settle_s == 0


def test_the_last_good_profile_is_kept_on_this_pc(tmp_path):
    assert ui_profile.load_cached(tmp_path) is ui_profile.BUILT_IN
    ui_profile.save_cached(tmp_path, {"version": 5, "body": {"profile_tab": ["Profil"]}})
    kept = ui_profile.load_cached(tmp_path)
    assert kept.version == 5 and kept.labels("profile_tab") == ("Profil",)
    ui_profile.cache_path(tmp_path).write_text('{"version": 6, "body": {"settle_s": 999}}', encoding="utf-8")
    assert ui_profile.load_cached(tmp_path) is ui_profile.BUILT_IN  # a bad file is never used


def test_the_runner_takes_a_new_valid_profile_and_keeps_the_old_one_otherwise(tmp_path):
    from agent.post_runner import PostRunner

    class Server:
        def __init__(self, answer):
            self.answer = answer

        def ui_profile(self, session):
            return self.answer

    logs = []
    runner = PostRunner(tmp_path, adb_factory=lambda: None, log=logs.append)
    runner.refresh_profile(Server({"version": 7, "body": {"verify_tries": 6}}), lambda: None)
    assert runner.profile.version == 7 and runner.profile.verify_tries == 6
    runner.refresh_profile(Server({"version": 8, "body": {"verify_tries": 99}}), lambda: None)
    assert runner.profile.version == 7 and any("ใช้ไม่ได้" in m for m in logs)
    runner.refresh_profile(Server(None), lambda: None)  # the server has none: keep what is in use
    assert runner.profile.version == 7
    assert PostRunner(tmp_path, adb_factory=lambda: None, log=logs.append).profile.version == 7  # after a restart
