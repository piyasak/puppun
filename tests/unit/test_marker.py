"""Q-49: the attempt marker is invisible: no digits or letters show in the caption."""

from agent import marker

POST = "437f6d0c-1234-4abc-8def-0123456789ab"


def test_the_marker_is_invisible_and_carries_the_attempt_code():
    mark = marker.hidden(POST)
    assert marker.visible("ทดสอบ #punpun" + mark) == "ทดสอบ #punpun"
    assert not any(ch.isalnum() or ch.isprintable() and not ch.isspace() and ch not in "⁠​‌" for ch in mark)
    assert marker.code(POST) == "437f6d" and len(mark) == 26
    assert marker.found("ทดสอบ" + mark, POST)


def test_another_attempt_never_matches():
    assert not marker.found("ทดสอบ" + marker.hidden("437f6e00-0000"), POST)
    assert not marker.found("ทดสอบ cf437f6d", POST)  # the old visible marker is not this one
