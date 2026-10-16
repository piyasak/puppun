"""Screen diagnostics on the Agent (PO 2026-10-16): read-only steps, and never in the way of a post."""

from __future__ import annotations

from agent import diagnostics


class Client:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def diagnostic_failure(self, session, serial, post_id, code):
        if self.fail:
            raise OSError("server down")
        self.calls.append(("failure", serial, post_id, code))
        return "d1"

    def diagnostic_file(self, session, diag_id, step, name, ext, data):
        self.calls.append(("file", step, name, ext))

    def diagnostic_done(self, session, diag_id, note=None, error=None):
        self.calls.append(("done", note, error))


class Ui:
    """Captures without a phone: a screenshot file is 'pulled', the last reading is kept."""

    def __init__(self):
        self.serial, self.last_xml, self.commands = "S", "<hierarchy/>", []
        self.adb = self

    def sh(self, command):
        self.commands.append(command)
        return ""

    def pull(self, serial, remote, local):
        local.write_bytes(b"\x89PNG\r\n\x1a\n1234")

    def read(self, check=True):
        return []


def test_a_failure_capture_uploads_the_screen_and_never_raises():
    client, logs = Client(), []
    diagnostics.capture_failure(client, None, Ui(), "SER", "post-1", "VERIFY_UNREADABLE", logs.append)
    assert client.calls[0] == ("failure", "SER", "post-1", "VERIFY_UNREADABLE")
    assert ("file", 0, "stopped", "png") in client.calls and ("file", 0, "stopped", "xml") in client.calls
    diagnostics.capture_failure(Client(fail=True), None, Ui(), "SER", "post-1", "X", logs.append)  # no exception
    assert any("ไม่ได้" in m for m in logs)


def test_an_unknown_check_is_refused_and_reported():
    client, logs = Client(), []
    diagnostics.run_requested(client, None, None, "S", {"id": "00000000-0000-4000-8000-000000000001",
                                                        "check": "type_and_post"}, None, logs.append,
                              ui_factory=lambda adb, serial: Ui())
    assert client.calls[-1][0] == "done" and "UNKNOWN_CHECK" in client.calls[-1][2]
