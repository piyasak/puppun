"""G4-01 / T11: slot arithmetic reproduces the PRD §5 examples and window edges (Asia/Bangkok)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clipflow_api.slots import SlotError, Window, normalize, parse_local, plan, zone

BKK = zone("Asia/Bangkok")
W = Window.parse("09:00", "21:00")


def local(slots):
    return [s.astimezone(BKK).strftime("%d %H:%M") for s in slots]


def test_prd_same_day_example():
    # เริ่ม 7 ต.ค. 2569 09:00; N=6; X=2; Window 09:00–21:00 → 09:00 … 19:00
    slots = plan(parse_local("2026-10-07T09:00", BKK), 6, 2, W, BKK)
    assert local(slots) == ["07 09:00", "07 11:00", "07 13:00", "07 15:00", "07 17:00", "07 19:00"]


def test_prd_next_day_example():  # T11
    # เริ่ม 7 ต.ค. 19:00; N=3; X=2 → 7 ต.ค. 19:00, 8 ต.ค. 09:00, 8 ต.ค. 11:00 (21:00 อยู่นอก Window)
    slots = plan(parse_local("2026-10-07T19:00", BKK), 3, 2, W, BKK)
    assert local(slots) == ["07 19:00", "08 09:00", "08 11:00"]


def test_slots_are_stored_in_utc():
    first = plan(parse_local("2026-10-07T09:00", BKK), 1, 2, W, BKK)[0]
    assert first.tzinfo == UTC and first == datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


@pytest.mark.parametrize("start, expected", [
    ("2026-10-07T08:59", "07 09:00"),  # before the window -> today's start
    ("2026-10-07T09:00", "07 09:00"),  # start is inclusive
    ("2026-10-07T20:59", "07 20:59"),  # just inside
    ("2026-10-07T21:00", "08 09:00"),  # end is exclusive -> next day
    ("2026-10-07T23:30", "08 09:00"),
    ("2026-10-07T00:00", "07 09:00"),
])
def test_window_edges(start, expected):
    assert local([normalize(parse_local(start, BKK), W, BKK)]) == [expected]


def test_next_slot_comes_from_the_previous_scheduled_slot_not_now():
    # Slots never depend on when posts actually ran: same input, same output, any time.
    a = plan(parse_local("2026-10-07T10:30", BKK), 4, 3, W, BKK)
    assert local(a) == ["07 10:30", "07 13:30", "07 16:30", "07 19:30"]
    assert all(b - a_ >= timedelta(hours=3) for a_, b in zip(a, a[1:], strict=False))


def test_interval_longer_than_the_window_skips_to_following_days():
    slots = plan(parse_local("2026-10-07T20:00", BKK), 3, 24, W, BKK)
    assert local(slots) == ["07 20:00", "08 20:00", "09 20:00"]


def test_end_24_00_means_end_of_day():
    w = Window.parse("18:00", "24:00")
    assert local(plan(parse_local("2026-10-07T22:00", BKK), 3, 1, w, BKK)) == ["07 22:00", "07 23:00", "08 18:00"]


@pytest.mark.parametrize("start, end", [("21:00", "09:00"), ("10:00", "10:00"), ("25:00", "26:00"), ("9", "10:00"),
                                        ("24:00", "24:00")])
def test_invalid_windows_are_refused(start, end):
    with pytest.raises(SlotError) as err:
        Window.parse(start, end)
    assert err.value.code == "WINDOW_INVALID"


@pytest.mark.parametrize("hours", [0, -1, 169])
def test_interval_must_be_a_positive_whole_number_of_hours(hours):
    with pytest.raises(SlotError) as err:
        plan(parse_local("2026-10-07T09:00", BKK), 2, hours, W, BKK)
    assert err.value.code == "INTERVAL_INVALID"


def test_only_supported_timezones():
    with pytest.raises(SlotError) as err:
        zone("America/New_York")
    assert err.value.code == "TIMEZONE_UNSUPPORTED"
