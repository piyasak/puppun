"""Posting slot arithmetic (PRD §5, §G; FR-09, FR-10). Pure functions, no database.

- A window is [start, end) in local wall-clock minutes of one day; end 1440 means 24:00
  (end of day). MVP windows never cross midnight (end > start).
- The first slot is the start time normalized forward into the window.
- Each next slot is the previous *scheduled* slot + X elapsed hours, normalized forward. It is
  never derived from when a post actually happened.
- Times are stored in UTC; the IANA timezone is kept with the series. The MVP accepts only
  timezones without DST transitions (E-39), so local wall-clock time is never ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

SUPPORTED_TIMEZONES = ("Asia/Bangkok",)  # no DST; widening this needs DST tests (PRD §G)
INTERVAL_CHOICES = (1, 2, 3, 6, 12, 24)  # FR-09 defaults in the UI; any integer 1..168 is accepted
MAX_INTERVAL_HOURS = 168


class SlotError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Window:
    start_min: int  # minutes after local midnight, inclusive
    end_min: int  # exclusive; 1440 = 24:00

    def __post_init__(self):
        if not (0 <= self.start_min < 1440 and 0 < self.end_min <= 1440):
            raise SlotError("WINDOW_INVALID", "ช่วงเวลาโพสต์ต้องอยู่ภายใน 00:00–24:00")
        if self.end_min <= self.start_min:
            raise SlotError("WINDOW_INVALID", "เวลาสิ้นสุดต้องหลังเวลาเริ่ม (ยังไม่รองรับช่วงข้ามเที่ยงคืน)")

    @classmethod
    def parse(cls, start: str, end: str) -> Window:
        return cls(_minutes(start, allow_24=False), _minutes(end, allow_24=True))

    def label(self) -> str:
        return f"{_hhmm(self.start_min)}–{_hhmm(self.end_min)}"


def _minutes(value: str, *, allow_24: bool) -> int:
    try:
        hh, mm = value.split(":")
        h, m = int(hh), int(mm)
    except ValueError:
        raise SlotError("WINDOW_INVALID", f"รูปแบบเวลาไม่ถูกต้อง: {value}") from None
    if allow_24 and (h, m) == (24, 0):
        return 1440
    if not (0 <= h < 24 and 0 <= m < 60):
        raise SlotError("WINDOW_INVALID", f"รูปแบบเวลาไม่ถูกต้อง: {value}")
    return h * 60 + m


def _hhmm(minutes: int) -> str:
    return "24:00" if minutes == 1440 else f"{minutes // 60:02d}:{minutes % 60:02d}"


def zone(name: str) -> ZoneInfo:
    if name not in SUPPORTED_TIMEZONES:
        raise SlotError("TIMEZONE_UNSUPPORTED", "ตอนนี้รองรับเฉพาะเวลาประเทศไทย (Asia/Bangkok)")
    return ZoneInfo(name)


def check_interval(hours: int) -> int:
    if not isinstance(hours, int) or not 1 <= hours <= MAX_INTERVAL_HOURS:
        raise SlotError("INTERVAL_INVALID", f"ระยะห่างต้องเป็นจำนวนเต็ม 1–{MAX_INTERVAL_HOURS} ชั่วโมง")
    return hours


def normalize(at: datetime, window: Window, tz: ZoneInfo) -> datetime:
    """The earliest instant >= `at` that falls inside the window (returned in UTC)."""
    local = at.astimezone(tz)
    minute = local.hour * 60 + local.minute + local.second / 60 + local.microsecond / 60_000_000
    day = local.date()
    if minute < window.start_min:
        pass  # later today, at the window start
    elif minute < window.end_min:
        return at.astimezone(UTC)
    else:
        day += timedelta(days=1)
    start = datetime.combine(day, time(window.start_min // 60, window.start_min % 60), tzinfo=tz)
    return start.astimezone(UTC)


def plan(start: datetime, count: int, interval_hours: int, window: Window, tz: ZoneInfo) -> list[datetime]:
    """`count` slots in UTC: first = start normalized, then previous slot + X hours normalized."""
    if count <= 0:
        raise SlotError("NO_CLIPS", "ไม่มีคลิปให้ตั้งเวลา")
    check_interval(interval_hours)
    slots = [normalize(start, window, tz)]
    while len(slots) < count:
        slots.append(normalize(slots[-1] + timedelta(hours=interval_hours), window, tz))
    return slots


def parse_local(value: str, tz: ZoneInfo) -> datetime:
    """'YYYY-MM-DDTHH:MM' wall-clock time in `tz` -> aware datetime (seconds dropped)."""
    try:
        naive = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise SlotError("START_INVALID", "รูปแบบวันเวลาเริ่มไม่ถูกต้อง") from None
    return naive.replace(tzinfo=tz)
