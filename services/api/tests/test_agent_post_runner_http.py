"""P5.2/P5.3 over real HTTP: the Agent post runner claims a due post, gets the bound file (own
render or verified download), pushes it with an on-phone hash check, finds it in the Gallery and
stops before Submit (dry-run). The phone is simulated here (ADB runner); the real POCO run is
test_real_device_post.py (opt-in)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

import pytest
from api_test_shop import FULL_DAY, items, set_times

from agent.adb import REMOTE_DIR, Adb
from agent.post_runner import PostRunner
from agent.server_client import ServerClient


class FakePhone:
    """Just enough of `adb` for transfer + Gallery discovery, with a real file store and sha256."""

    def __init__(self, serial: str, corrupt_push=False, gallery=True, on_push=None, tiktok="40.0.0"):
        self.serial, self.corrupt_push, self.gallery, self.on_push = serial, corrupt_push, gallery, on_push
        self.tiktok = tiktok  # what `doctor` reads (compatibility matrix, D03)
        self.files: dict[str, bytes] = {}
        self.pushed: list[str] = []

    def run(self, args: list[str]) -> str:
        if args[:2] == ["devices", "-l"]:
            return f"List of devices attached\n{self.serial}  device model:25078PC3EG transport_id:1\n"
        if args[2] == "push":
            data = Path(args[3]).read_bytes()
            self.files[args[4]] = data[:-1] + b"x" if self.corrupt_push else data
            self.pushed.append(args[4])
            if self.on_push:
                self.on_push()
            return "1 file pushed"
        cmd = args[3]
        if cmd.startswith("getprop "):
            return {"ro.serialno": self.serial, "ro.product.model": "25078PC3EG",
                    "ro.build.version.release": "15", "ro.build.version.sdk": "35"}[cmd.split()[1]] + "\n"
        if cmd == "pm list packages":
            return "package:com.ss.android.ugc.trill\npackage:com.android.adbkeyboard\n"
        if cmd.startswith("dumpsys package"):
            return f"    versionName={self.tiktok}\n"
        if cmd.startswith("dumpsys power"):
            return "mWakefulness=Awake\n"
        if cmd.startswith("command -v sha256sum"):
            return "/system/bin/sha256sum\n"
        if cmd.startswith("sha256sum "):
            path = re.search(r"'(.+)'", cmd).group(1)
            return f"{hashlib.sha256(self.files[path]).hexdigest()}  {path}\n"
        if cmd.startswith("mv -f "):
            src, dst = re.findall(r"'([^']+)'", cmd)
            self.files[dst] = self.files.pop(src)
            return ""
        if cmd.startswith("rm -f "):
            for path in re.findall(r"'([^']+)'", cmd):
                self.files.pop(path, None)
            return ""
        if cmd.startswith("content query"):
            name = re.search(r"_display_name='([^']+)'", cmd).group(1)
            listed = self.gallery and any(p == f"{REMOTE_DIR}/{name}" for p in self.files)
            return f"Row: 0 _display_name={name}\n" if listed else "No result found.\n"
        return ""  # mkdir/touch, media scanner broadcast


@pytest.fixture
def setup(shop, app, server_url, tmp_path):
    def make(phone_kw=None, own_copy=True, ui=None):
        job_id, clip_ids = shop.job(clips=1)
        series = shop.create(job_id, **FULL_DAY).json()
        set_times(app, series["id"], [-1])
        data_dir = tmp_path / "agent-data"
        if own_copy:  # the PC that rendered the clip still has it (Q-15)
            own = data_dir / "clips" / job_id / "clip_01.mp4"
            own.parent.mkdir(parents=True, exist_ok=True)
            own.write_bytes(shop.clip_bytes)
        phone = FakePhone(shop.serial, **(phone_kw or {}))
        client = ServerClient(server_url)
        session = client.authenticate(shop.acc.username, shop.token, shop.w.installation_id)
        logs = []
        runner = PostRunner(data_dir, lambda: Adb(phone.run), log=logs.append, retry_wait_s=0.1,
                            ui_rehearsal=ui is not None, ui_factory=(lambda adb, serial: ui) if ui else None)
        return {"series": series, "phone": phone, "runner": runner, "data_dir": data_dir, "logs": logs,
                "run": lambda: runner.run_once(client, lambda: session)}
    return make


def journal(data_dir: Path) -> list[str]:
    return [json.loads(line)["state"] for line in (data_dir / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]


def test_dry_run_with_the_agents_own_render(shop, setup):
    s = setup()
    assert s["run"]() == "DRY_RUN_DONE"
    item = items(shop, s["series"]["id"])[0]
    assert item["state"] == "DRY_RUN_DONE" and item["started_at"] and item["submitted_at"] is None
    phone = s["phone"]
    assert phone.pushed[0].startswith(f"{REMOTE_DIR}/.incoming/")  # staged, verified, then renamed
    assert phone.files == {}  # the test file is removed from the phone afterwards
    assert journal(s["data_dir"]) == ["CLAIMED", "TRANSFERRING", "PREPARING", "CANCELLED"]
    assert not (s["data_dir"] / "downloads").exists()  # no download needed
    assert any("หยุดก่อนกดโพสต์" in line for line in s["logs"])


def test_dry_run_downloads_and_verifies_the_bound_file(shop, setup):
    s = setup(own_copy=False)
    assert s["run"]() == "DRY_RUN_DONE"
    sha = s["series"]["items"][0]["clip_sha256"]
    cached = s["data_dir"] / "downloads" / f"{sha}.mp4"
    assert hashlib.sha256(cached.read_bytes()).hexdigest() == sha


def test_a_transfer_that_arrives_damaged_is_never_offered_to_the_gallery(shop, setup):
    s = setup({"corrupt_push": True})
    assert s["run"]() == "SCHEDULED"  # retryable: back to the same slot on the server
    item = items(shop, s["series"]["id"])[0]
    assert (item["state"], item["reason"]) == ("SCHEDULED", "TRANSFER_FAILED")
    assert s["phone"].files == {} and journal(s["data_dir"])[-1] == "RETRYABLE_FAILED"


def test_clip_missing_from_the_gallery_stops_before_submit(shop, setup):
    s = setup({"gallery": False})
    assert s["run"]() == "SCHEDULED"
    assert items(shop, s["series"]["id"])[0]["reason"] == "GALLERY_NOT_FOUND"
    assert s["phone"].files == {}


def test_losing_the_lease_mid_transfer_stops_the_post(shop, app, setup):
    from api_test_shop import expire
    from sqlalchemy import update

    from clipflow_api.models import ScheduleItem

    holder = {}

    def lose_lease():
        expire(app, holder["id"])
        with app.state.db.sessionmaker() as db:  # another Agent took it over
            db.execute(update(ScheduleItem).where(ScheduleItem.id == uuid.UUID(holder["id"]))
                       .values(lease_session_id=None))
            db.commit()

    s = setup({"on_push": lose_lease})
    holder["id"] = s["series"]["items"][0]["id"]
    assert s["run"]() == "stopped"
    assert journal(s["data_dir"])[-1] == "CANCELLED" and s["phone"].files == {}


def test_nothing_is_claimed_without_a_ready_phone(shop, setup):
    s = setup()
    s["phone"].serial = "OTHERPHONE"  # a phone this Workspace never registered
    assert s["run"]() is None
    assert items(shop, s["series"]["id"])[0]["state"] == "SCHEDULED"


class FakeUi:
    """Stands in for TikTokUi (its own logic is tested in tests/unit/test_tiktok_ui.py)."""

    def __init__(self, account="handle0", stop=None):
        self.account, self.stop, self.calls = account, stop, []

    def check_account(self, expected):
        self.calls.append(("account", expected))
        if self.stop:
            raise self.stop
        if expected != self.account:
            from agent.tiktok_ui import UiStop

            raise UiStop("ACCOUNT_MISMATCH", f"phone is logged in as @{self.account}")
        return self.account

    def open_post_screen(self, media_id):
        self.calls.append(("open", media_id))

    def set_only_me(self):
        self.calls.append(("only_me",))

    def type_caption(self, caption):
        self.calls.append(("caption", caption))

    def close(self):
        self.calls.append(("close",))


class GalleryWithIds(FakePhone):
    def run(self, args):
        if len(args) > 3 and args[3].startswith("content query") and "_display_name='" not in args[3]:
            return "".join(f"Row: {i} _id={60 + i}, _display_name={p.rsplit('/', 1)[-1]}\n"
                           for i, p in enumerate(self.files))
        return super().run(args)


def test_dry_run_with_tiktok_rehearsal_checks_account_and_text(shop, setup, monkeypatch):
    import test_agent_post_runner_http as me

    monkeypatch.setattr(me, "FakePhone", GalleryWithIds)
    ui = FakeUi()
    s = setup(ui=ui)
    assert s["run"]() == "DRY_RUN_DONE"
    kinds = [c[0] for c in ui.calls]
    assert kinds == ["account", "open", "only_me", "caption", "close"]
    caption = dict((c[0], c[1]) for c in ui.calls if len(c) > 1)["caption"]
    meta = shop.acc.get(f"/v1/clips/{s['series']['items'][0]['clip_id']}").json()["metadata"]
    assert caption == " ".join([meta["caption"], *meta["hashtags"]]).strip()  # the approved version's text
    assert ui.calls[0] == ("account", "handle0")


def test_wrong_account_on_the_phone_parks_the_post(shop, setup, monkeypatch):  # G5-03
    import test_agent_post_runner_http as me

    monkeypatch.setattr(me, "FakePhone", GalleryWithIds)
    s = setup(ui=FakeUi(account="someone_else"))
    assert s["run"]() == "NEEDS_ACTION"
    item = items(shop, s["series"]["id"])[0]
    assert (item["state"], item["reason"]) == ("NEEDS_ACTION", "ACCOUNT_MISMATCH")
    assert journal(s["data_dir"])[-1] == "NEEDS_ACTION" and s["phone"].files == {}


def test_login_wall_or_captcha_parks_the_post(shop, setup, monkeypatch):  # G5-03
    import test_agent_post_runner_http as me

    from agent.tiktok_ui import UiStop

    monkeypatch.setattr(me, "FakePhone", GalleryWithIds)
    s = setup(ui=FakeUi(stop=UiStop("CAPTCHA", "verification screen")))
    assert s["run"]() == "NEEDS_ACTION"
    assert items(shop, s["series"]["id"])[0]["reason"] == "CAPTCHA"


def test_untested_tiktok_version_is_never_driven(shop, setup, monkeypatch):  # D03, T25
    import test_agent_post_runner_http as me

    monkeypatch.setattr(me, "FakePhone", lambda serial, **kw: GalleryWithIds(serial, tiktok="41.2.0", **kw))
    ui = FakeUi()
    s = setup(ui=ui)
    assert s["run"]() == "NEEDS_ACTION"
    assert items(shop, s["series"]["id"])[0]["reason"] == "UNSUPPORTED_DEVICE" and ui.calls == []
