"""The Agent's settings window (PO 2026-10-10): `punpun-agent settings`.

One window instead of typing in a console: link this PC with a pairing code from the web, choose
the clips folder and the videos folder with a folder picker, and choose whether the Agent starts
with Windows. The logic lives in agent/settings.py; this file only draws it.

It follows the web app's dark theme (apps/web/src/index.css: colours, 16 px cards, 8 px controls,
the indigo primary) rather than grey Windows controls: cards and buttons are drawn on canvases,
messages appear inside the window, and the title bar is dark on Windows 10/11. tkinter ships with
Python, so the packaged Agent needs nothing more.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font

from agent import clips_folder, settings
from agent.identity import default_data_dir
from agent.updater import default_install_dir

ASSETS = Path(__file__).resolve().parent / "assets"
THAI_FONT = "Leelawadee UI"  # Windows' Thai UI font; Tk's default draws Thai too small to read

# apps/web/src/index.css (dark, the web's default)
BG = "#050506"
CARD = "#0c0c0f"
CARD_BORDER = "#1c1c21"
FIELD = "#0f0f12"
FIELD_BORDER = "#3a3c43"
FOCUS = "#8b93e6"
TEXT = "#ededef"
MUTED = "#8a8f98"
PRIMARY = "#5e6ad2"
PRIMARY_HOVER = "#6f7ae0"
SECONDARY = "#16161b"
SECONDARY_HOVER = "#1f1f26"
SUCCESS = "#4cc38a"
DANGER = "#f07178"
DISABLED = "#2a2a31"


def use_thai_font(root: tk.Misc, size: int = 10) -> str:
    family = THAI_FONT if THAI_FONT in font.families(root) else font.nametofont("TkDefaultFont", root).actual("family")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
        font.nametofont(name, root).configure(family=family, size=size)
    return family


def dark_title_bar(root: tk.Tk) -> None:
    """Windows 10 (20H1+) / 11: DWMWA_USE_IMMERSIVE_DARK_MODE, so the frame matches the window."""
    if sys.platform != "win32":
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
    except (AttributeError, OSError):
        pass


def rounded(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw) -> int:
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
              x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


class Button(tk.Canvas):
    """A rounded button like the web's .btn-primary / .btn-secondary."""

    def __init__(self, parent, text: str, command, *, primary=False, bg=CARD, width=None, height=36, family=None):
        self.f = font.Font(family=family, size=10, weight="bold" if primary else "normal")
        width = width or self.f.measure(text) + 36
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, cursor="hand2")
        self.text, self.command, self.primary, self.enabled = text, command, primary, True
        self.colors = (PRIMARY, PRIMARY_HOVER) if primary else (SECONDARY, SECONDARY_HOVER)
        self.shape = rounded(self, 1, 1, width - 1, height - 1, 8, fill=self.colors[0],
                             outline=PRIMARY if primary else FIELD_BORDER)
        self.label = self.create_text(width / 2, height / 2, text=text, fill=TEXT, font=self.f)
        self.bind("<Enter>", lambda e: self.enabled and self.itemconfigure(self.shape, fill=self.colors[1]))
        self.bind("<Leave>", lambda e: self.enabled and self.itemconfigure(self.shape, fill=self.colors[0]))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())
        self.bind("<Return>", lambda e: self.enabled and self.command())
        self.configure(takefocus=1)

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self.itemconfigure(self.shape, fill=self.colors[0] if on else DISABLED,
                           outline=(PRIMARY if self.primary else FIELD_BORDER) if on else DISABLED)
        self.itemconfigure(self.label, fill=TEXT if on else MUTED)
        self.configure(cursor="hand2" if on else "arrow")


class Card(tk.Frame):
    """A web-style card: rounded, a faint border, drawn behind the content frame."""

    def __init__(self, parent, title: str, family: str):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=CARD)
        self.body.pack(fill="both", expand=True, padx=14, pady=12)
        tk.Label(self.body, text=title, bg=CARD, fg=TEXT, font=(family, 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.bind("<Configure>", self._draw)

    def _draw(self, _event=None) -> None:
        self.canvas.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        rounded(self.canvas, 1, 1, w - 2, h - 2, 16, fill=CARD, outline=CARD_BORDER)


def entry(parent, var: tk.StringVar, width: int, family: str, mono=False) -> tk.Entry:
    return tk.Entry(parent, textvariable=var, width=width, bg=FIELD, fg=TEXT, insertbackground=TEXT,
                    relief="flat", highlightthickness=1, highlightbackground=FIELD_BORDER, highlightcolor=FOCUS,
                    font=("Consolas", 13) if mono else (family, 10), disabledbackground=FIELD)


class SettingsWindow:
    def __init__(self, root: tk.Tk, data_dir: Path, default_server: str, launcher: Path | None):
        self.root, self.data_dir, self.launcher = root, data_dir, launcher
        self.started = False  # "บันทึกและเริ่มทำงาน" pressed
        state = settings.load(data_dir)
        family = self.family = use_thai_font(root)
        root.title("ตั้งค่า punpun Agent")
        root.configure(bg=BG)
        root.resizable(False, False)
        self.images = {}
        if (ASSETS / "mark-96.png").is_file():
            self.images["icon"] = tk.PhotoImage(file=str(ASSETS / "mark-96.png"))
            self.images["mark"] = tk.PhotoImage(file=str(ASSETS / "mark-40.png"))
            root.iconphoto(True, self.images["icon"])
        dark_title_bar(root)
        page = tk.Frame(root, bg=BG)
        page.pack(fill="both", expand=True, padx=20, pady=16)

        # --- header: logo + name ---
        header = tk.Frame(page, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        if "mark" in self.images:
            tk.Label(header, image=self.images["mark"], bg=BG).pack(side="left", padx=(0, 10))
        names = tk.Frame(header, bg=BG)
        names.pack(side="left")
        tk.Label(names, text="punpun Agent", bg=BG, fg=TEXT, font=(family, 15, "bold")).pack(anchor="w")
        tk.Label(names, text="ตั้งค่าเครื่องนี้: บัญชี โฟลเดอร์ และการเริ่มทำงาน", bg=BG, fg=MUTED,
                 font=(family, 9)).pack(anchor="w")

        # --- account ---
        account = Card(page, "บัญชี", family)
        account.pack(fill="x", pady=6)
        a = account.body
        self.muted(a, "Server").grid(row=1, column=0, sticky="w", pady=4)
        self.server = tk.StringVar(value=state.server or default_server)
        entry(a, self.server, 44, family).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(10, 0), ipady=5)
        self.linked = tk.StringVar(value=self._linked_text(state))
        self.linked_label = tk.Label(a, textvariable=self.linked, bg=CARD, font=(family, 9),
                                     fg=SUCCESS if state.paired else DANGER)
        self.linked_label.grid(row=2, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=(2, 6))
        self.muted(a, "รหัสเชื่อมต่อ").grid(row=3, column=0, sticky="w")
        self.code = tk.StringVar()
        code_entry = entry(a, self.code, 12, family, mono=True)
        code_entry.grid(row=3, column=1, sticky="w", padx=(10, 0), ipady=4)
        self.pair_button = Button(a, "เชื่อมต่อ", self.pair, primary=True, family=family)
        self.pair_button.grid(row=3, column=2, sticky="e", padx=(10, 0))
        self.muted(a, "สร้างรหัสบนเว็บ: หน้า Agent → \"สร้างรหัสเชื่อมต่อ\" (ใช้ได้ 10 นาที ครั้งเดียว)", 9).grid(
            row=4, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=(6, 0))
        code_entry.bind("<Return>", lambda e: self.pair())

        # --- folders ---
        folders = Card(page, "โฟลเดอร์", family)
        folders.pack(fill="x", pady=6)
        f = folders.body
        self.muted(f, "เก็บคลิปที่ตัดแล้ว").grid(row=1, column=0, sticky="w", pady=4)
        self.clips = tk.StringVar(value=state.clips_dir)
        entry(f, self.clips, 34, family).grid(row=1, column=1, sticky="ew", padx=10, ipady=5)
        Button(f, "เลือก…", lambda: self.pick(self.clips), family=family).grid(row=1, column=2)
        self.free = tk.StringVar()
        self.free_label = tk.Label(f, textvariable=self.free, bg=CARD, font=(family, 9))
        self.free_label.grid(row=2, column=1, columnspan=2, sticky="w", padx=10, pady=(0, 8))
        self.muted(f, "วิดีโอของฉัน").grid(row=3, column=0, sticky="w", pady=4)
        self.media = tk.StringVar(value=state.media_dir or "")
        entry(f, self.media, 34, family).grid(row=3, column=1, sticky="ew", padx=10, ipady=5)
        Button(f, "เลือก…", lambda: self.pick(self.media), family=family).grid(row=3, column=2)
        self.muted(f, "ไฟล์ที่เลือกเป็น \"ไฟล์วิดีโอบนเครื่อง Agent\" ตอนสร้างงาน ต้องอยู่ในโฟลเดอร์นี้", 9).grid(
            row=4, column=1, columnspan=2, sticky="w", padx=10)
        self.clips.trace_add("write", lambda *_: self.show_free())
        self.show_free()

        # --- phone screens on this PC (PO 2026-10-10) ---
        screens = Card(page, "หน้าจอโทรศัพท์", family)
        screens.pack(fill="x", pady=6)
        sc = screens.body
        self.show_screens = tk.BooleanVar(value=state.show_screens)
        self.screens_control = tk.StringVar(value="control" if state.screens_control else "view")
        self.check(sc, "แสดงหน้าจอโทรศัพท์บน PC เรียงตามชื่อโทรศัพท์บนเว็บ", self.show_screens).grid(
            row=1, column=0, columnspan=3, sticky="w")
        modes = tk.Frame(sc, bg=CARD)
        modes.grid(row=2, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=(4, 0))
        for value, text in (("control", "ควบคุมได้ (ล็อกเป็นดูอย่างเดียวระหว่าง Agent โพสต์บนเครื่องนั้น)"),
                            ("view", "ดูอย่างเดียว")):
            tk.Radiobutton(modes, text=text, value=value, variable=self.screens_control, bg=CARD, fg=TEXT,
                           activebackground=CARD, activeforeground=TEXT, selectcolor=FIELD, highlightthickness=0,
                           bd=0, font=(family, 10), cursor="hand2").pack(anchor="w")
        from agent.screens import find_scrcpy

        if find_scrcpy() is None:
            self.muted(sc, "ไม่พบ scrcpy ในเครื่องนี้ — ติดตั้ง Agent ด้วยไฟล์ setup เวอร์ชันล่าสุด", 9).grid(
                row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- start with Windows + actions ---
        self.autostart = tk.BooleanVar(value=state.autostart)
        box = tk.Checkbutton(page, text="เริ่ม punpun Agent เองเมื่อเปิดเครื่อง (login Windows)", variable=self.autostart,
                             bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT, selectcolor=FIELD,
                             highlightthickness=0, bd=0, font=(family, 10), cursor="hand2")
        box.pack(anchor="w", pady=(10, 4))
        if launcher is None:
            box.configure(state="disabled", disabledforeground=MUTED)  # from source: nothing to start at login

        self.status = tk.StringVar()
        self.status_label = tk.Label(page, textvariable=self.status, bg=BG, fg=MUTED, font=(family, 9),
                                     wraplength=500, justify="left")
        self.status_label.pack(anchor="w", pady=(2, 0))
        actions = tk.Frame(page, bg=BG)
        actions.pack(fill="x", pady=(10, 0))
        self.start_button = Button(actions, "บันทึกและเริ่มทำงาน", self.save_and_start, primary=True, bg=BG,
                                   family=family)
        self.start_button.pack(side="right")
        Button(actions, "บันทึก", self.save, bg=BG, family=family).pack(side="right", padx=8)
        if launcher is None:
            self.start_button.set_enabled(False)
        code_entry.focus_set()

    def check(self, parent, text: str, var: tk.BooleanVar) -> tk.Checkbutton:
        return tk.Checkbutton(parent, text=text, variable=var, bg=CARD, fg=TEXT, activebackground=CARD,
                              activeforeground=TEXT, selectcolor=FIELD, highlightthickness=0, bd=0,
                              font=(self.family, 10), cursor="hand2")

    def muted(self, parent, text: str, size: int = 10) -> tk.Label:
        return tk.Label(parent, text=text, bg=CARD, fg=MUTED if size < 10 else TEXT, font=(self.family, size))

    @staticmethod
    def _linked_text(state: settings.State) -> str:
        if state.paired and state.username:
            return f"✓ เชื่อมต่อแล้ว: {state.username}"
        return "ยังไม่ได้เชื่อมต่อบัญชี — ใส่รหัสเชื่อมต่อจากเว็บ"

    def say(self, text: str, ok: bool | None = None) -> None:
        """Messages stay in the window (no grey Windows pop-ups)."""
        self.status.set(text)
        self.status_label.configure(fg=MUTED if ok is None else SUCCESS if ok else DANGER)

    def pick(self, var: tk.StringVar) -> None:
        start = var.get() if var.get() and Path(var.get()).exists() else str(Path.home())
        chosen = filedialog.askdirectory(parent=self.root, initialdir=start, mustexist=False)
        if chosen:
            var.set(str(Path(chosen)))

    def show_free(self) -> None:
        try:
            gb = clips_folder.free_bytes(Path(self.clips.get())) / 1024**3
        except (OSError, ValueError):
            self.free.set("")
            return
        ok = gb * 1024**3 >= clips_folder.MIN_FREE_BYTES
        self.free.set(f"ว่าง {gb:.1f} GB" + ("" if ok else " — ไม่พอ: ต้องมีอย่างน้อย 5 GB จึงจะรับงานใหม่"))
        self.free_label.configure(fg=SUCCESS if ok else DANGER)

    def pair(self) -> None:
        self.pair_button.set_enabled(False)
        self.say("กำลังเชื่อมต่อ…")
        server, code = self.server.get().strip(), self.code.get()
        outcome: list = []

        def work():  # off the window's thread, so the window stays responsive; tkinter is touched only below
            try:
                outcome.append((settings.pair(self.data_dir, server, code), None))
            except settings.SettingsError as exc:
                outcome.append((None, str(exc)))

        def wait():
            if outcome:
                self._paired(*outcome[0])
            else:
                self.root.after(100, wait)

        threading.Thread(target=work, daemon=True).start()
        wait()

    def _paired(self, result: dict | None, error: str | None) -> None:
        self.pair_button.set_enabled(True)
        if error:
            self.say(f"เชื่อมต่อไม่สำเร็จ: {error}", ok=False)
            return
        self.code.set("")
        self.linked.set(f"✓ เชื่อมต่อแล้ว: {result['username']} • Environment {result['environment']}")
        self.linked_label.configure(fg=SUCCESS)
        self.say("เชื่อมต่อแล้ว เลือกโฟลเดอร์แล้วกดบันทึก", ok=True)

    def save(self) -> bool:
        try:
            settings.save_folders(self.data_dir, self.clips.get(), self.media.get())
            settings.save_screens(self.data_dir, self.show_screens.get(), self.screens_control.get() == "control")
            if self.launcher is not None and self.autostart.get() != settings.autostart_on():
                settings.set_autostart(self.autostart.get(), self.launcher)
        except settings.SettingsError as exc:
            self.say(f"บันทึกไม่ได้: {exc}", ok=False)
            return False
        except OSError as exc:
            self.say(f"บันทึกไม่ได้: สร้าง shortcut เริ่มเองตอนเปิดเครื่องไม่ได้ ({exc})", ok=False)
            return False
        self.say("✓ บันทึกการตั้งค่าแล้ว", ok=True)
        return True

    def save_and_start(self) -> None:
        if self.save():
            self.started = True
            self.root.destroy()


def run(data_dir: Path | None = None, default_server: str = "https://punpun-staging.onrender.com") -> int:
    import subprocess

    if sys.platform == "win32":
        with contextlib.suppress(AttributeError, OSError):  # crisp text on scaled displays
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    data_dir = data_dir or default_data_dir()
    launcher = default_install_dir() / "punpun-agent.cmd"
    root = tk.Tk()
    window = SettingsWindow(root, data_dir, default_server, launcher if launcher.is_file() else None)
    root.mainloop()
    if window.started and window.launcher is not None:
        # The Agent in its own console window, which stays open (as the desktop shortcut does)
        subprocess.Popen(["cmd.exe", "/k", str(window.launcher), "connect"],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)  # type: ignore[attr-defined]
    return 0
