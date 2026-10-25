"""
Auto Clicker — customtkinter + pynput  (with Minecraft Java hit mode)
Run:      py auto_clicker.py
Requires: py -m pip install customtkinter pynput
"""

import ctypes
import json
import math
import os
import queue
import random
import re
import sys
import threading
import time
import traceback
from pathlib import Path

import customtkinter as ctk
from pynput import keyboard, mouse

# ───────────────────────── Design tokens ─────────────────────────
BG = "#0F1115"
SURFACE = "#171A21"
RAISED = "#222732"
BORDER = "#2C3240"
TEXT = "#E8EAF0"        # 14:1 on SURFACE
MUTED = "#9AA3B2"       # 6.8:1 on SURFACE
ACCENT = "#4A63D8"      # white text 5.5:1
ACCENT_HOVER = "#5B74E8"
STOP = "#D64545"        # white text 4.8:1
STOP_HOVER = "#E55B5B"
OK_TEXT = "#5EE0A0"
ERR_TEXT = "#FF8A8A"
# greyed-out (locked) look
DIM_BG = "#1A1D24"
DIM_BORDER = "#232834"
DIM_SEL = "#2E3442"
DIM_TEXT = "#6B7385"

if sys.platform.startswith("win"):
    UI_FONT, MONO_FONT = "Segoe UI", "Consolas"
elif sys.platform == "darwin":
    UI_FONT, MONO_FONT = "Helvetica Neue", "Menlo"
else:
    UI_FONT, MONO_FONT = "DejaVu Sans", "DejaVu Sans Mono"

# ───────────────────────── Settings & limits ─────────────────────────
BUTTONS = {
    "Left": mouse.Button.left,
    "Middle": mouse.Button.middle,
    "Right": mouse.Button.right,
}
MODIFIERS = {
    "shift", "shift_l", "shift_r", "ctrl", "ctrl_l", "ctrl_r",
    "alt", "alt_l", "alt_r", "alt_gr", "cmd", "cmd_l", "cmd_r",
}
MIN_INTERVAL = 1
MAX_MS = 3_600_000          # 1 hour
MAX_CLICKS = 100_000_000
MAX_DELAY = 30              # seconds
CORNER = 3                  # px: safety-stop zone in the top-left corner

# Minecraft Java: attack speed (attacks per second) of each weapon class.
# Full charge takes 20 / speed game ticks (1 tick = 50 ms).
WEAPONS = {
    "Sword": 1.6,
    "Axe: wood/stone/copper": 0.8,
    "Axe: iron": 0.9,
    "Axe: gold/diamond/netherite": 1.0,
    "Trident": 1.1,
    "Mace": 0.6,
    "Fist": 4.0,
}
TICK_MS = 50
MC_MARGIN_MS = 10           # small safety margin so a hit never lands a hair early


def mc_interval(speed):
    """Milliseconds between hits for a fully charged attack."""
    return math.ceil(20 / speed - 1e-9) * TICK_MS + MC_MARGIN_MS


DEFAULTS = {
    "button": "Left",
    "interval": 100,
    "clicks": 0,
    "double": False,
    "jitter_on": False,
    "jitter": 50,
    "hotkey": "f6",
    "topmost": False,
    "failsafe": True,
    "start_delay": 3,
    "mc_mode": False,
    "mc_weapon": "Sword",
}
MANUAL_KEYS = ("button", "interval", "double", "jitter_on", "jitter")

CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "AutoClicker"
CONFIG_PATH = CONFIG_DIR / "settings.json"
LOG_PATH = CONFIG_DIR / "error.log"


def load_settings():
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key, default in DEFAULTS.items():
                value = data.get(key, default)
                if isinstance(default, bool):
                    cfg[key] = value if isinstance(value, bool) else default
                elif isinstance(default, int):
                    ok = isinstance(value, int) and not isinstance(value, bool)
                    cfg[key] = value if ok else default
                else:
                    cfg[key] = value if isinstance(value, str) else default
    except (OSError, ValueError):
        pass
    if cfg["button"] not in BUTTONS:
        cfg["button"] = DEFAULTS["button"]
    if cfg["mc_weapon"] not in WEAPONS:
        cfg["mc_weapon"] = DEFAULTS["mc_weapon"]
    cfg["interval"] = min(max(cfg["interval"], MIN_INTERVAL), MAX_MS)
    cfg["clicks"] = min(max(cfg["clicks"], 0), MAX_CLICKS)
    cfg["jitter"] = min(max(cfg["jitter"], 0), MAX_MS)
    cfg["start_delay"] = min(max(cfg["start_delay"], 0), MAX_DELAY)
    if not cfg["hotkey"] or cfg["hotkey"] in MODIFIERS:
        cfg["hotkey"] = DEFAULTS["hotkey"]
    return cfg


def save_settings(cfg):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        pass


def log_error(text):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
    except OSError:
        pass


def effective(cfg):
    """The settings the engine actually uses (Minecraft mode overrides the manual ones)."""
    if not cfg.get("mc_mode"):
        return cfg
    speed = WEAPONS.get(cfg.get("mc_weapon"), WEAPONS["Sword"])
    return {**cfg, "button": "Left", "interval": mc_interval(speed),
            "double": False, "jitter_on": False, "jitter": 0}


# ───────────────────────── Key helpers ─────────────────────────
def key_id(key):
    """Stable string id for a pynput key (None if unusable)."""
    if isinstance(key, keyboard.Key):
        return key.name
    ch = getattr(key, "char", None)
    if ch and ch.isprintable():
        return ch.lower()
    vk = getattr(key, "vk", None)
    return f"vk{vk}" if vk is not None else None


def key_label(kid):
    if kid.startswith("vk"):
        return f"Key {kid[2:]}"
    if re.fullmatch(r"f\d+", kid) or len(kid) == 1:
        return kid.upper()
    return kid.replace("_", " ").title()


def set_timer_resolution(on):
    """Ask Windows for 1 ms timer ticks (default is ~15 ms) for accurate short intervals."""
    if sys.platform.startswith("win"):
        try:
            winmm = ctypes.windll.winmm
            (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
        except Exception:
            pass


def fmt_time(seconds):
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class ConfigError(ValueError):
    def __init__(self, message, widget=None, page="main"):
        super().__init__(message)
        self.widget = widget
        self.page = page


# ───────────────────────── Click engine ─────────────────────────
class ClickEngine:
    """Clicks on a background thread. The UI only reads its public state."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self.count = 0
        self.phase = "idle"        # idle | countdown | running
        self.reason = ""           # done | stopped | failsafe | error
        self.error = ""
        self.warmup_end = 0.0
        self.started_at = 0.0
        self.ended_at = 0.0

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed(self):
        if not self.started_at:
            return 0.0
        end = time.perf_counter() if self.phase == "running" else self.ended_at
        return max(0.0, end - self.started_at)

    def start(self, cfg, warmup_s):
        if self.active:
            return
        self._stop.clear()
        self.count = 0
        self.reason = self.error = ""
        self.started_at = self.ended_at = 0.0
        self.warmup_end = time.monotonic() + warmup_s
        self.phase = "countdown" if warmup_s else "running"
        self._thread = threading.Thread(target=self._run, args=(cfg, warmup_s), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _sleep_until(self, target):
        """Interruptible, drift-free wait. Returns True if stop was requested."""
        while True:
            remaining = target - time.perf_counter()
            if remaining <= 0:
                return self._stop.is_set()
            if remaining > 0.003:
                if self._stop.wait(remaining - 0.002):
                    return True
            elif self._stop.is_set():   # spin only for the last ~2 ms
                return True

    @staticmethod
    def _in_corner(ctrl):
        x, y = ctrl.position
        return 0 <= x <= CORNER and 0 <= y <= CORNER

    def _run(self, cfg, warmup_s):
        set_timer_resolution(True)
        try:
            ctrl = mouse.Controller()
            if warmup_s and self._stop.wait(warmup_s):
                self.reason = "stopped"
                return
            interval = cfg["interval"] / 1000
            jitter = cfg["jitter"] / 1000 if cfg["jitter_on"] else 0
            presses = 2 if cfg["double"] else 1
            limit = cfg["clicks"]
            button = BUTTONS[cfg["button"]]
            failsafe = cfg["failsafe"]

            self.phase = "running"
            self.started_at = next_t = time.perf_counter()
            while True:
                if failsafe and self._in_corner(ctrl):
                    self.reason = "failsafe"
                    return
                ctrl.click(button, presses)
                self.count += 1
                if limit and self.count >= limit:
                    self.reason = "done"
                    return
                next_t += interval + (random.uniform(0, jitter) if jitter else 0)
                now = time.perf_counter()
                if next_t < now:            # fell behind: resync instead of bursting
                    next_t = now
                if self._sleep_until(next_t):
                    self.reason = "stopped"
                    return
        except Exception as exc:            # e.g. missing OS permission
            self.error = str(exc) or exc.__class__.__name__
            self.reason = "error"
            log_error(traceback.format_exc())
        finally:
            self.ended_at = time.perf_counter()
            self.phase = "idle"
            set_timer_resolution(False)


# ───────────────────────────── UI ─────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG)
        self.title("Auto Clicker")
        self.geometry("500x700")
        self.resizable(False, False)

        self.settings = load_settings()
        self.hotkey_id = self.settings["hotkey"]
        self._manual = {k: self.settings[k] for k in MANUAL_KEYS}
        self.engine = ClickEngine()
        self.events = queue.SimpleQueue()
        self.session_active = False
        self.capturing = False
        self._held_key = None
        self._fast = False
        self._run_interval = 0
        self._run_mc = False
        self._showing_hint = False
        self._listener_warned = False
        self._last_check = 0.0
        self.row_labels = {}
        self._cache = {"count": None, "stats": None, "status": None}
        self._digits = (self.register(lambda s: s.isdigit() or s == ""), "%P")

        self._build()
        self._apply(self.settings)
        self._start_hotkey_listener()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll)

    # ───────── layout ─────────
    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Auto Clicker", text_color=TEXT,
                     font=ctk.CTkFont(UI_FONT, 22, "bold")).grid(row=0, column=0, sticky="w")
        self.tabs = ctk.CTkSegmentedButton(
            header, values=["Clicker", "Options"], command=self._switch_page,
            width=190, height=32, font=ctk.CTkFont(UI_FONT, 13),
            fg_color=RAISED, unselected_color=RAISED, unselected_hover_color=BORDER,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, text_color=TEXT)
        self.tabs.set("Clicker")
        self.tabs.grid(row=0, column=1, sticky="e")

        pages = ctk.CTkFrame(self, fg_color="transparent")
        pages.grid(row=1, column=0, sticky="ew", padx=24)
        pages.grid_columnconfigure(0, weight=1)
        self.page_main = ctk.CTkFrame(pages, fg_color="transparent")
        self.page_opts = ctk.CTkFrame(pages, fg_color="transparent")
        for p in (self.page_main, self.page_opts):
            p.grid(row=0, column=0, sticky="ew")
            p.grid_columnconfigure(0, weight=1)
        self.page_opts.grid_remove()

        self._build_main(self.page_main)
        self._build_options(self.page_opts)

        self.main_btn = ctk.CTkButton(
            self, text="", height=48, corner_radius=12,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF",
            font=ctk.CTkFont(UI_FONT, 17, "bold"), command=lambda: self.toggle(from_button=True))
        self.main_btn.grid(row=2, column=0, sticky="ew", padx=24, pady=(14, 22))

    def _build_main(self, page):
        counter = self._card(page, 0, (0, 12))
        counter.grid_columnconfigure(0, weight=1)
        self.count_label = ctk.CTkLabel(counter, text="0", text_color=TEXT,
                                        font=ctk.CTkFont(MONO_FONT, 52, "bold"))
        self.count_label.grid(row=0, column=0, pady=(14, 0))
        ctk.CTkLabel(counter, text="CLICKS", text_color=MUTED,
                     font=ctk.CTkFont(UI_FONT, 12, "bold")).grid(row=1, column=0)
        self.stats_label = ctk.CTkLabel(counter, text="0:00  ·  0.0 clicks/s", text_color=MUTED,
                                        font=ctk.CTkFont(MONO_FONT, 12))
        self.stats_label.grid(row=2, column=0, pady=(2, 0))
        self.status = ctk.CTkLabel(counter, text="", text_color=MUTED, height=38,
                                   font=ctk.CTkFont(UI_FONT, 13), wraplength=400)
        self.status.grid(row=3, column=0, pady=(6, 12))

        s = self._card(page, 1, (0, 0))
        s.grid_columnconfigure(1, weight=1)

        # Minecraft hit mode: weapon picker + master switch
        box = ctk.CTkFrame(s, fg_color="transparent")
        self.weapon_menu = ctk.CTkOptionMenu(
            box, values=list(WEAPONS), width=210, height=34, anchor="w",
            dynamic_resizing=False, command=self._on_weapon,
            fg_color=RAISED, button_color=BORDER, button_hover_color=ACCENT,
            dropdown_fg_color=SURFACE, dropdown_hover_color=RAISED,
            dropdown_text_color=TEXT, text_color=TEXT, text_color_disabled=DIM_TEXT,
            font=ctk.CTkFont(UI_FONT, 12), dropdown_font=ctk.CTkFont(UI_FONT, 12))
        self.weapon_menu.set("Sword")
        self.mc_sw = self._switch(box, command=self._on_mc_toggle)
        self.weapon_menu.grid(row=0, column=0, padx=(0, 8))
        self.mc_sw.grid(row=0, column=1)
        self._row(s, 0, "Minecraft hit", box)

        self.button_seg = ctk.CTkSegmentedButton(
            s, values=list(BUTTONS), height=34, font=ctk.CTkFont(UI_FONT, 13),
            fg_color=RAISED, unselected_color=RAISED, unselected_hover_color=BORDER,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, text_color=TEXT,
            text_color_disabled=DIM_TEXT)
        self._row(s, 1, "Mouse button", self.button_seg, key="button")
        self.interval_entry = self._entry(s)
        self._row(s, 2, "Interval (ms)", self.interval_entry, key="interval")
        self.count_entry = self._entry(s)
        self._row(s, 3, "Clicks (0 = ∞)", self.count_entry)
        self.double_sw = self._switch(s)
        self._row(s, 4, "Double click", self.double_sw, key="double")
        self.jitter_sw = self._switch(s, command=self._refresh_states)
        self._row(s, 5, "Random extra delay", self.jitter_sw, key="jitter_on")
        self.jitter_entry = self._entry(s)
        self._row(s, 6, "Up to (ms)", self.jitter_entry, last=True, key="jitter")

    def _build_options(self, page):
        c = self._card(page, 0, (0, 10))
        c.grid_columnconfigure(1, weight=1)
        self.hotkey_btn = ctk.CTkButton(
            c, text="", width=130, height=34, fg_color=RAISED, hover_color=BORDER,
            text_color=TEXT, text_color_disabled=DIM_TEXT,
            font=ctk.CTkFont(MONO_FONT, 14, "bold"), command=self._begin_capture)
        self._row(c, 0, "Start / stop key", self.hotkey_btn)
        self.delay_entry = self._entry(c)
        self._row(c, 1, "Start delay (s)", self.delay_entry)
        self.topmost_sw = self._switch(c, command=self._on_topmost)
        self._row(c, 2, "Always on top", self.topmost_sw)
        self.failsafe_sw = self._switch(c, command=self._save)
        self._row(c, 3, "Corner safety stop", self.failsafe_sw, last=True)

        self.opt_note = ctk.CTkLabel(
            page, text_color=MUTED, justify="left", anchor="w", wraplength=440,
            font=ctk.CTkFont(UI_FONT, 12),
            text="Click the key box, then press the new key. Esc cancels.\n"
                 "F-keys are safest: letters would also trigger while you type elsewhere.\n"
                 "Start delay applies only when you start with the on-screen button.\n"
                 "Safety stop: move the cursor to the top-left corner to halt clicking.")
        self.opt_note.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.reset_btn = ctk.CTkButton(
            page, text="Reset to defaults", height=34, fg_color="transparent",
            border_width=1, border_color=BORDER, hover_color=RAISED, text_color=TEXT,
            text_color_disabled=DIM_TEXT, font=ctk.CTkFont(UI_FONT, 13),
            command=self._reset_defaults)
        self.reset_btn.grid(row=2, column=0, sticky="ew")

    def _card(self, parent, row, pady):
        f = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=14,
                         border_width=1, border_color=BORDER)
        f.grid(row=row, column=0, sticky="ew", pady=pady)
        return f

    def _row(self, parent, r, label, widget, last=False, key=None):
        top = 12 if r == 0 else 4
        bottom = 12 if last else 4
        lab = ctk.CTkLabel(parent, text=label, text_color=TEXT, anchor="w",
                           font=ctk.CTkFont(UI_FONT, 14))
        lab.grid(row=r, column=0, sticky="w", padx=(16, 8), pady=(top, bottom))
        widget.grid(row=r, column=1, sticky="e", padx=(8, 16), pady=(top, bottom))
        if key:
            self.row_labels[key] = lab

    def _entry(self, parent):
        e = ctk.CTkEntry(parent, width=96, height=34, justify="center",
                         fg_color=RAISED, border_color=BORDER, text_color=TEXT,
                         font=ctk.CTkFont(MONO_FONT, 14),
                         validate="key", validatecommand=self._digits)
        e.bind("<Key>", lambda _e, w=e: w.configure(border_color=BORDER), add="+")
        return e

    def _switch(self, parent, command=None):
        return ctk.CTkSwitch(parent, text="", width=46, command=command,
                             progress_color=ACCENT, fg_color=RAISED,
                             button_color=TEXT, button_hover_color="#FFFFFF")

    # ───────── greyed-out styling ─────────
    @staticmethod
    def _dim_entry(w, dim):
        w.configure(fg_color=DIM_BG if dim else RAISED,
                    text_color=DIM_TEXT if dim else TEXT,
                    border_color=DIM_BORDER if dim else BORDER)

    @staticmethod
    def _dim_switch(w, dim):
        w.configure(progress_color=DIM_SEL if dim else ACCENT,
                    fg_color=DIM_BG if dim else RAISED,
                    button_color=DIM_TEXT if dim else TEXT,
                    button_hover_color=DIM_TEXT if dim else "#FFFFFF")

    @staticmethod
    def _dim_seg(w, dim):
        w.configure(selected_color=DIM_SEL if dim else ACCENT,
                    selected_hover_color=DIM_SEL if dim else ACCENT_HOVER,
                    unselected_color=DIM_BG if dim else RAISED,
                    unselected_hover_color=DIM_BG if dim else BORDER,
                    fg_color=DIM_BG if dim else RAISED,
                    text_color=DIM_TEXT if dim else TEXT)

    @staticmethod
    def _dim_menu(w, dim):
        w.configure(fg_color=DIM_BG if dim else RAISED,
                    button_color=DIM_SEL if dim else BORDER,
                    text_color=DIM_TEXT if dim else TEXT)

    def _refresh_states(self):
        """Single place that decides what is editable and how it looks."""
        idle = not self.session_active
        mc = bool(self.mc_sw.get())
        jitter_on = bool(self.jitter_sw.get())
        free = idle and not mc                    # manual click settings
        state = lambda ok: "normal" if ok else "disabled"

        self._dim_seg(self.button_seg, mc)
        self.button_seg.configure(state=state(free))
        self._dim_entry(self.interval_entry, mc)
        self.interval_entry.configure(state=state(free))
        self._dim_switch(self.double_sw, mc)
        self.double_sw.configure(state=state(free))
        self._dim_switch(self.jitter_sw, mc)
        self.jitter_sw.configure(state=state(free))

        jitter_ok = free and jitter_on
        self._dim_entry(self.jitter_entry, mc or not jitter_on)
        self.jitter_entry.configure(state=state(jitter_ok))

        for key, dim in (("button", mc), ("interval", mc), ("double", mc),
                         ("jitter_on", mc), ("jitter", mc or not jitter_on)):
            self.row_labels[key].configure(text_color=DIM_TEXT if dim else TEXT)

        self._dim_menu(self.weapon_menu, not mc)
        self.weapon_menu.configure(state=state(idle and mc))
        self.mc_sw.configure(state=state(idle))
        for w in (self.count_entry, self.delay_entry, self.hotkey_btn, self.reset_btn):
            w.configure(state=state(idle))

    # ───────── settings <-> widgets ─────────
    def _put(self, entry, value):
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, str(value))

    @staticmethod
    def _set_switch(sw, on):
        sw.select() if on else sw.deselect()

    def _write_manual(self, m):
        self.button_seg.set(m["button"])
        self._put(self.interval_entry, m["interval"])
        self._put(self.jitter_entry, m["jitter"])
        self._set_switch(self.double_sw, m["double"])
        self._set_switch(self.jitter_sw, m["jitter_on"])

    def _mc_ms(self):
        return mc_interval(WEAPONS.get(self.weapon_menu.get(), WEAPONS["Sword"]))

    def _write_mc(self):
        """Show the values Minecraft mode forces (they are greyed out)."""
        self.button_seg.set("Left")
        self._put(self.interval_entry, self._mc_ms())
        self._set_switch(self.double_sw, False)
        self._set_switch(self.jitter_sw, False)

    def _snapshot_manual(self):
        """Read the manual widgets leniently, keeping old values where the field is invalid."""
        m = dict(self._manual)
        m["button"] = self.button_seg.get()
        m["double"] = bool(self.double_sw.get())
        m["jitter_on"] = bool(self.jitter_sw.get())
        for key, entry, lo in (("interval", self.interval_entry, MIN_INTERVAL),
                               ("jitter", self.jitter_entry, 0)):
            raw = entry.get().strip()
            if raw.isdigit():
                m[key] = min(max(int(raw), lo), MAX_MS)
        return m

    def _apply(self, cfg):
        self._manual = {k: cfg[k] for k in MANUAL_KEYS}
        self._write_manual(self._manual)
        self._put(self.count_entry, cfg["clicks"])
        self._put(self.delay_entry, cfg["start_delay"])
        self.weapon_menu.set(cfg["mc_weapon"])
        for sw, on in ((self.mc_sw, cfg["mc_mode"]), (self.topmost_sw, cfg["topmost"]),
                       (self.failsafe_sw, cfg["failsafe"])):
            self._set_switch(sw, on)
        if cfg["mc_mode"]:
            self._write_mc()
        self.hotkey_id = cfg["hotkey"]
        self._refresh_states()
        self._on_topmost(save=False)
        self._refresh_hotkey_labels()

    def _num(self, entry, label, lo, hi, empty=None, page="main"):
        raw = entry.get().strip()
        if raw == "":
            if empty is None:
                raise ConfigError(f"{label} is required.", entry, page)
            return empty
        value = int(raw)
        if not lo <= value <= hi:
            raise ConfigError(f"{label} must be between {lo:,} and {hi:,}.", entry, page)
        return value

    def _collect(self):
        mc = bool(self.mc_sw.get())
        if mc:
            manual = dict(self._manual)   # widgets show Minecraft values; keep the user's own
        else:
            manual = {
                "button": self.button_seg.get(),
                "interval": self._num(self.interval_entry, "Interval", MIN_INTERVAL, MAX_MS),
                "double": bool(self.double_sw.get()),
                "jitter_on": bool(self.jitter_sw.get()),
                "jitter": self._manual["jitter"],
            }
            if manual["jitter_on"]:
                manual["jitter"] = self._num(self.jitter_entry, "Random delay", 0, MAX_MS, empty=0)
        cfg = {
            **manual,
            "clicks": self._num(self.count_entry, "Click count", 0, MAX_CLICKS, empty=0),
            "hotkey": self.hotkey_id,
            "topmost": bool(self.topmost_sw.get()),
            "failsafe": bool(self.failsafe_sw.get()),
            "start_delay": self._num(self.delay_entry, "Start delay", 0, MAX_DELAY,
                                     empty=0, page="options"),
            "mc_mode": mc,
            "mc_weapon": self.weapon_menu.get(),
        }
        self._manual = manual
        return cfg

    def _save(self):
        try:
            self.settings = self._collect()
        except ConfigError:
            self.settings = {**self.settings, **self._manual,
                             "hotkey": self.hotkey_id,
                             "topmost": bool(self.topmost_sw.get()),
                             "failsafe": bool(self.failsafe_sw.get()),
                             "mc_mode": bool(self.mc_sw.get()),
                             "mc_weapon": self.weapon_menu.get()}
        save_settings(self.settings)

    def _reset_defaults(self):
        if self.session_active:
            return
        self._end_capture()
        self._apply(DEFAULTS)
        self._save()
        self._opt_say("Settings restored to defaults.", OK_TEXT)

    def _on_topmost(self, save=True):
        self.attributes("-topmost", bool(self.topmost_sw.get()))
        if save:
            self._save()

    # ───────── Minecraft mode ─────────
    def _on_mc_toggle(self):
        if self.mc_sw.get():
            self._manual = self._snapshot_manual()   # remember what the user had
            self._write_mc()
        else:
            self._write_manual(self._manual)         # give it all back, editable again
        self._refresh_states()
        self._refresh_hotkey_labels()
        self._save()

    def _on_weapon(self, _value=None):
        if self.mc_sw.get():
            self._put(self.interval_entry, self._mc_ms())
            self._refresh_states()
            self._refresh_hotkey_labels()
        self._save()

    # ───────── messages ─────────
    def _say(self, text, color=MUTED):
        self._showing_hint = False
        if self._cache["status"] != (text, color):
            self._cache["status"] = (text, color)
            self.status.configure(text=text, text_color=color)

    def _opt_say(self, text, color=MUTED):
        self.opt_note.configure(text=text, text_color=color)

    def _idle_hint(self):
        key = key_label(self.hotkey_id)
        if self.mc_sw.get():
            self._say(f"Minecraft mode — a full-charge hit every {self._mc_ms()} ms. "
                      f"Aim, then press {key}")
        else:
            self._say(f"Ready — move the cursor to your target, then press {key}")
        self._showing_hint = True

    def _switch_page(self, name):
        if name == "Options":
            self.page_main.grid_remove()
            self.page_opts.grid()
        else:
            self._end_capture()
            self.page_opts.grid_remove()
            self.page_main.grid()

    def _refresh_hotkey_labels(self):
        label = key_label(self.hotkey_id)
        if not self.capturing:
            self.hotkey_btn.configure(text=label)
        if self.session_active:
            self.main_btn.configure(text=f"Stop  ·  {label}")
        else:
            self.main_btn.configure(text=f"Start  ·  {label}")
            if self._showing_hint or self._cache["status"] is None:
                self._idle_hint()

    def _show_error(self, err):
        if err.widget is not None:
            err.widget.configure(border_color=ERR_TEXT)
            err.widget.focus_set()
        page = "Options" if err.page == "options" else "Clicker"
        self.tabs.set(page)
        self._switch_page(page)
        self._say(str(err), ERR_TEXT)
        self._opt_say(str(err), ERR_TEXT)

    # ───────── shortcut capture ─────────
    def _begin_capture(self):
        if self.session_active or self.capturing:
            return
        if not self.listener.is_alive():
            self._opt_say("Global shortcuts aren't available on this system.", ERR_TEXT)
            return
        self.capturing = True
        self.hotkey_btn.configure(text="Press a key…", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                  text_color="#FFFFFF")
        self._opt_say("Press the new key now. Esc cancels.", MUTED)

    def _end_capture(self):
        if self.capturing:
            self.capturing = False
            self.hotkey_btn.configure(fg_color=RAISED, hover_color=BORDER, text_color=TEXT)
            self._refresh_hotkey_labels()

    def _handle_capture(self, key):
        if not self.capturing:
            return
        kid = key_id(key)
        self._end_capture()
        if kid is None:
            self._opt_say("That key can't be used. Try another one.", ERR_TEXT)
        elif kid == "esc":
            self._opt_say("Cancelled — shortcut unchanged.")
        elif kid in MODIFIERS:
            self._opt_say("Modifier keys (Ctrl, Shift, Alt) can't be used alone.", ERR_TEXT)
        else:
            self.hotkey_id = kid
            self._refresh_hotkey_labels()
            self._save()
            warn = " (letters also trigger while typing elsewhere)" if len(kid) == 1 else ""
            self._opt_say(f"Shortcut set to {key_label(kid)}.{warn}", OK_TEXT)

    # ───────── start / stop ─────────
    def toggle(self, from_button=False):
        if self.capturing:
            return
        if self.engine.active:
            self.engine.stop()
            return
        try:
            cfg = self._collect()
        except ConfigError as err:
            self._show_error(err)
            return

        self.settings = cfg
        save_settings(cfg)
        run_cfg = effective(cfg)
        self._fast = run_cfg["interval"] < 10
        self._run_interval = run_cfg["interval"]
        self._run_mc = cfg["mc_mode"]
        self.session_active = True
        self._refresh_states()
        self.main_btn.configure(text=f"Stop  ·  {key_label(self.hotkey_id)}",
                                fg_color=STOP, hover_color=STOP_HOVER)
        self.engine.start(run_cfg, cfg["start_delay"] if from_button else 0)

    def _finish(self):
        self.session_active = False
        self._refresh_states()
        self.main_btn.configure(text=f"Start  ·  {key_label(self.hotkey_id)}",
                                fg_color=ACCENT, hover_color=ACCENT_HOVER)
        n, why = self.engine.count, self.engine.reason
        if why == "error":
            self._say(f"Couldn't click: {self.engine.error}", ERR_TEXT)
        elif why == "done":
            self._say(f"Done — {n:,} clicks", OK_TEXT)
        elif why == "failsafe":
            self._say(f"Safety stop — cursor reached the corner. {n:,} clicks")
        else:
            self._say(f"Stopped — {n:,} clicks")

    # ───────── main loop ─────────
    def _poll(self):
        try:
            while True:
                kind, *payload = self.events.get_nowait()
                if kind == "toggle":
                    self.toggle()
                elif kind == "capture":
                    self._handle_capture(payload[0])
        except queue.Empty:
            pass

        try:
            eng = self.engine
            if eng.count != self._cache["count"]:
                self._cache["count"] = eng.count
                self.count_label.configure(text=f"{eng.count:,}")
            elapsed = eng.elapsed
            rate = eng.count / elapsed if elapsed >= 1 else 0.0
            stats = f"{fmt_time(elapsed)}  ·  {rate:.1f} clicks/s"
            if stats != self._cache["stats"]:
                self._cache["stats"] = stats
                self.stats_label.configure(text=stats)

            if self.session_active and not eng.active:
                self._finish()
            elif eng.active:
                key = key_label(self.hotkey_id)
                if eng.phase == "countdown":
                    left = max(1, math.ceil(eng.warmup_end - time.monotonic()))
                    self._say(f"Starting in {left} s — move the cursor to your target")
                elif self._run_mc:
                    self._say(f"Minecraft mode — a hit every {self._run_interval} ms · "
                              f"press {key} to stop", OK_TEXT)
                elif self._fast:
                    self._say("Running at under 10 ms — some apps may skip clicks", OK_TEXT)
                else:
                    self._say(f"Running — press {key} to stop", OK_TEXT)

            now = time.monotonic()
            if now - self._last_check > 2:
                self._last_check = now
                if not self.listener.is_alive() and not self._listener_warned:
                    self._listener_warned = True
                    self._say("Shortcut unavailable — use the Start button.", ERR_TEXT)
        finally:
            self.after(50, self._poll)

    # ───────── global shortcut ─────────
    def _start_hotkey_listener(self):
        def on_press(key):
            kid = key_id(key)
            if kid is None:
                return
            if self.capturing:
                self._held_key = kid          # swallow auto-repeat of the new key
                self.events.put(("capture", key))
            elif kid == self.hotkey_id and self._held_key != kid:
                self._held_key = kid
                self.events.put(("toggle",))

        def on_release(key):
            if key_id(key) == self._held_key:
                self._held_key = None

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.daemon = True
        try:
            self.listener.start()
        except Exception:
            log_error(traceback.format_exc())

    # ───────── safety nets ─────────
    def report_callback_exception(self, exc, val, tb):
        log_error("".join(traceback.format_exception(exc, val, tb)))
        self.engine.stop()
        self._say(f"Unexpected error: {val}", ERR_TEXT)

    def _on_close(self):
        self.engine.stop()
        self._save()
        try:
            self.listener.stop()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
