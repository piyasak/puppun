"""Phone screens on the PC (PO 2026-10-10): order, grid and the view-only lock. Logic only; the real
windows are checked with the QA phone."""

from __future__ import annotations

from agent.screens import Cell, Phone, ScreenWall, layout, ordered


def test_order_follows_the_names_on_the_web():
    named = [{"serial": "B", "display_name": "เครื่อง 10", "expected_account": "shop10"},
             {"serial": "a", "display_name": "เครื่อง 2", "expected_account": None},
             {"serial": "C", "display_name": None, "model": "25078PC3EG"}]
    phones = ordered([("adb-c", "C"), ("adb-b", "B"), ("adb-a", "A"), ("adb-x", "X")], named)
    assert [p.serial for p in phones] == ["adb-a", "adb-b", "adb-c", "adb-x"]  # 2 before 10; unnamed last
    assert phones[0].title == "เครื่อง 2" and phones[1].title == "เครื่อง 10 • @shop10"
    assert phones[2].title == "25078PC3EG" and phones[3].title == "adb-x"


def test_grid_fills_the_screen_in_reading_order_without_overlap():
    cells = layout(5, (0, 0, 1920, 1040))
    assert len(cells) == 5
    assert all(c.x >= 0 and c.y >= 0 and c.x + c.width <= 1920 and c.y + c.height <= 1040 for c in cells)
    assert cells[0].y == cells[1].y and cells[0].x < cells[1].x  # left to right
    for a in cells:
        for b in cells:
            if a is not b:
                assert a.x + a.width <= b.x or b.x + b.width <= a.x or a.y + a.height <= b.y or b.y + b.height <= a.y
    assert abs(cells[0].width / cells[0].height - 9 / 19.5) < 0.01  # portrait phone shape
    one = layout(1, (0, 0, 1920, 1040))[0]
    assert one.height > cells[0].height  # one phone gets a bigger window


class Proc:
    def __init__(self, args):
        self.args, self.done = args, False

    def poll(self):
        return 0 if self.done else None

    def terminate(self):
        self.done = True


def wall(control=True):
    opened = []

    def popen(args, **kw):
        opened.append(Proc(args))
        assert kw["env"]["ADB"] == r"C:\agent\adb\adb.exe"  # scrcpy uses the Agent's own adb (E-51)
        return opened[-1]

    return ScreenWall("scrcpy.exe", r"C:\agent\adb\adb.exe", control=control, popen=popen,
                      area=(0, 0, 1920, 1040)), opened


def test_windows_open_in_order_and_follow_changes():
    w, opened = wall()
    w.show([Phone("A", "เครื่อง 1"), Phone("B", "เครื่อง 2")])
    assert [p.args[2] for p in opened] == ["A", "B"] and all("--no-control" not in p.args for p in opened)
    assert "--no-audio" in opened[0].args and not any("stay-awake" in a for a in opened[0].args)
    w.show([Phone("A", "เครื่อง 1"), Phone("B", "เครื่อง 2")])
    assert len(opened) == 2  # nothing changed: windows stay
    w.show([Phone("B", "เครื่อง 2")])  # A unplugged: closed, B gets the whole screen
    assert opened[0].done and opened[1].done and opened[2].args[2] == "B"
    w.close()
    assert all(p.done for p in opened)


def test_a_phone_the_agent_works_on_is_view_only_meanwhile():
    w, opened = wall()
    w.show([Phone("A", "เครื่อง 1")])
    with w.locked("A"):
        assert opened[0].done and "--no-control" in opened[1].args
        assert opened[1].args[opened[1].args.index("--window-title") + 1].endswith("(ดูอย่างเดียว)")
    assert opened[1].done and "--no-control" not in opened[2].args  # control is given back


def test_view_only_mode_never_gives_control():
    w, opened = wall(control=False)
    w.show([Phone("A", "เครื่อง 1")])
    with w.locked("A"):
        pass
    assert len(opened) == 1 and "--no-control" in opened[0].args


def test_layout_cell_type():
    assert isinstance(layout(2, (0, 0, 800, 600))[0], Cell)


def _port(proc):
    return next(int(a.split("=", 1)[1]) for a in proc.args if a.startswith("--port="))


def test_every_window_has_its_own_port():
    # PO 2026-10-21: right after the wall opened, two windows showed one phone (scrcpy instances started
    # together shared a tunnel port).
    w, opened = wall()
    w.show([Phone("A", "เครื่อง 1"), Phone("B", "เครื่อง 2"), Phone("C", "เครื่อง 3")])
    ports = [_port(p) for p in opened]
    assert len(set(ports)) == 3 and all(27200 <= p < 27300 for p in ports)  # never scrcpy's default range
    with w.locked("B"):  # reopened view-only: a new port, the old window may still be closing
        assert _port(opened[3]) not in ports
    assert len({_port(p) for p in opened[3:]} | {ports[0], ports[2]}) == len(opened[3:]) + 2
    w.close()
    w.show([Phone("A", "เครื่อง 1")])
    assert _port(opened[-1]) == 27200  # ports are free again after close
