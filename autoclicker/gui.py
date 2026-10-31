"""CustomTkinter UI with 2-mode presets, editable CPS in Default mode, DPI-safe scroll, and tray icon."""

import json
import math
import queue
import threading
import time
import traceback
import urllib.request
import webbrowser

import customtkinter as ctk
from pynput import keyboard, mouse

try:
    import pystray
    from PIL import Image
except ImportError:
    pystray = None
    Image = None

from autoclicker import __app_name__, __repo_name__, __repo_owner__, __version__
from autoclicker.config import (
    ACCENT,
    ACCENT_HOVER,
    ACTION_MODES,
    BG,
    BORDER,
    BUTTON_NAMES,
    DEFAULTS,
    DIM_BG,
    DIM_BORDER,
    DIM_SEL,
    DIM_TEXT,
    ERR_TEXT,
    LOCATION_MODES,
    MANUAL_KEYS,
    MAX_CLICKS,
    MAX_CPS,
    MAX_DELAY,
    MAX_MINUTES,
    MAX_MS,
    MIN_CPS,
    MIN_INTERVAL,
    MODIFIERS,
    MONO_FONT,
    MUTED,
    OK_TEXT,
    PRESET_MODES,
    RAISED,
    STOP,
    STOP_HOVER,
    SURFACE,
    TEXT,
    UI_FONT,
    WEAPONS,
    ConfigError,
    cps_to_interval_ms,
    effective,
    fmt_time,
    get_resource_path,
    interval_ms_to_cps,
    key_label,
    load_presets,
    load_settings,
    log_error,
    mc_interval,
    merge_preset_preserving_globals,
    save_presets,
    save_settings,
)
from autoclicker.engine import ClickEngine, key_id


class App(ctk.CTk):
    STATS_INTERVAL_S = 0.25  # 4 updates per second instead of 20

    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG)
        self.title(f"{__app_name__} v{__version__}")
        self._set_window_icon()
        self._configure_dpi_geometry()

        self.settings = load_settings()
        self.presets = load_presets()
        self.hotkey_id = self.settings["hotkey"]
        self.record_key_id = self.settings.get("record_key", "f8")
        self._manual = {k: self.settings[k] for k in MANUAL_KEYS}
        self.engine = ClickEngine()
        self.events = queue.SimpleQueue()
        self.session_active = False
        self.capturing = False
        self._syncing_fields = False
        self._held_key = None
        self._fast = False
        self._run_interval = 0
        self._run_mc = False
        self._run_hold = False
        self._showing_hint = False
        self._listener_warned = False
        self._last_check = 0.0
        self._last_stats_update = 0.0
        self._tray_icon = None
        self.row_labels = {}
        self._cache = {"count": None, "stats": None, "status": None}
        self._digits = (self.register(lambda s: s.isdigit() or s == ""), "%P")
        self._float_valid = (
            self.register(lambda s: s == "" or s.replace(".", "", 1).isdigit()),
            "%P",
        )

        self._build()
        self._apply(self.settings)
        self._start_hotkey_listener()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close_request)
        self.after(50, self._poll)

    def _set_window_icon(self):
        ico = get_resource_path("assets/icon.ico")
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except (OSError, RuntimeError):
                pass

    def _configure_dpi_geometry(self):
        """Calculate window height dynamically based on screen height so Start is never cut off at 150% scaling."""
        self.update_idletasks()
        screen_h = self.winfo_screenheight() or 1080
        screen_w = self.winfo_screenwidth() or 1920
        width = 520
        height = min(740, max(500, int(screen_h * 0.84)))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(480, 460)
        self.resizable(True, True)

    # ───────── layout ─────────
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=f"Auto Clicker  v{__version__}",
            text_color=TEXT,
            font=ctk.CTkFont(UI_FONT, 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.tabs = ctk.CTkSegmentedButton(
            header,
            values=["Clicker", "Options"],
            command=self._switch_page,
            width=190,
            height=32,
            font=ctk.CTkFont(UI_FONT, 13),
            fg_color=RAISED,
            unselected_color=RAISED,
            unselected_hover_color=BORDER,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            text_color=TEXT,
        )
        self.tabs.set("Clicker")
        self.tabs.grid(row=0, column=1, sticky="e")

        pages = ctk.CTkFrame(self, fg_color="transparent")
        pages.grid(row=1, column=0, sticky="nsew", padx=20)
        pages.grid_columnconfigure(0, weight=1)
        pages.grid_rowconfigure(0, weight=1)

        self.page_main = ctk.CTkScrollableFrame(
            pages, fg_color="transparent", scrollbar_button_color=RAISED, scrollbar_button_hover_color=BORDER
        )
        self.page_opts = ctk.CTkScrollableFrame(
            pages, fg_color="transparent", scrollbar_button_color=RAISED, scrollbar_button_hover_color=BORDER
        )
        for p in (self.page_main, self.page_opts):
            p.grid(row=0, column=0, sticky="nsew")
            p.grid_columnconfigure(0, weight=1)
        self.page_opts.grid_remove()

        self._build_main(self.page_main)
        self._build_options(self.page_opts)

        self.main_btn = ctk.CTkButton(
            self,
            text="",
            height=48,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(UI_FONT, 17, "bold"),
            command=lambda: self.toggle(from_button=True),
        )
        self.main_btn.grid(row=2, column=0, sticky="ew", padx=24, pady=(10, 18))

    def _build_main(self, page):
        counter = self._card(page, 0, (0, 10))
        counter.grid_columnconfigure(0, weight=1)
        self.count_label = ctk.CTkLabel(
            counter, text="0", text_color=TEXT, font=ctk.CTkFont(MONO_FONT, 48, "bold")
        )
        self.count_label.grid(row=0, column=0, pady=(12, 0))
        ctk.CTkLabel(
            counter, text="CLICKS", text_color=MUTED, font=ctk.CTkFont(UI_FONT, 12, "bold")
        ).grid(row=1, column=0)
        self.stats_label = ctk.CTkLabel(
            counter,
            text="0:00  ·  0.0 clicks/s  ·  CPU 0.0%",
            text_color=MUTED,
            font=ctk.CTkFont(MONO_FONT, 12),
        )
        self.stats_label.grid(row=2, column=0, pady=(2, 0))
        self.telemetry_label = ctk.CTkLabel(
            counter,
            text="Timing & CPU stats appear after each run",
            text_color=MUTED,
            font=ctk.CTkFont(MONO_FONT, 11),
        )
        self.telemetry_label.grid(row=3, column=0, pady=(2, 0))
        self.status = ctk.CTkLabel(
            counter,
            text="",
            text_color=MUTED,
            height=36,
            font=ctk.CTkFont(UI_FONT, 13),
            wraplength=410,
        )
        self.status.grid(row=4, column=0, pady=(4, 10))

        # 2-Mode Preset card: strictly "Default" (customizable & savable) and "Sword (Minecraft)" (fixed)
        pcard = self._card(page, 1, (0, 10))
        pcard.grid_columnconfigure(0, weight=1)
        prow = ctk.CTkFrame(pcard, fg_color="transparent")
        prow.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 10))
        prow.grid_columnconfigure(0, weight=1)
        self.preset_seg = ctk.CTkSegmentedButton(
            prow,
            values=list(PRESET_MODES),
            height=34,
            command=self._on_preset_select,
            fg_color=RAISED,
            unselected_color=RAISED,
            unselected_hover_color=BORDER,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            text_color=TEXT,
            text_color_disabled=DIM_TEXT,
            font=ctk.CTkFont(UI_FONT, 13, "bold"),
        )
        self.preset_seg.set("Default")
        self.preset_seg.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.save_preset_btn = ctk.CTkButton(
            prow,
            text="Save Default",
            width=116,
            height=34,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            text_color_disabled=DIM_TEXT,
            font=ctk.CTkFont(UI_FONT, 12, "bold"),
            command=self._save_default_preset,
        )
        self.save_preset_btn.grid(row=0, column=1)

        # Settings card
        s = self._card(page, 2, (0, 10))
        s.grid_columnconfigure(1, weight=1)

        # Minecraft hit mode: weapon picker + master switch
        box = ctk.CTkFrame(s, fg_color="transparent")
        self.weapon_menu = ctk.CTkOptionMenu(
            box,
            values=list(WEAPONS),
            width=200,
            height=34,
            anchor="w",
            dynamic_resizing=False,
            command=self._on_weapon,
            fg_color=RAISED,
            button_color=BORDER,
            button_hover_color=ACCENT,
            dropdown_fg_color=SURFACE,
            dropdown_hover_color=RAISED,
            dropdown_text_color=TEXT,
            text_color=TEXT,
            text_color_disabled=DIM_TEXT,
            font=ctk.CTkFont(UI_FONT, 12),
            dropdown_font=ctk.CTkFont(UI_FONT, 12),
        )
        self.weapon_menu.set("Sword")
        self.mc_sw = self._switch(box, command=self._on_mc_toggle)
        self.weapon_menu.grid(row=0, column=0, padx=(0, 8))
        self.mc_sw.grid(row=0, column=1)
        self._row(s, 0, "Minecraft hit", box)

        self.custom_speed_entry = ctk.CTkEntry(
            s,
            width=96,
            height=34,
            justify="center",
            fg_color=RAISED,
            border_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(MONO_FONT, 14),
            validate="key",
            validatecommand=self._float_valid,
        )
        self.custom_speed_entry.bind(
            "<Key>", lambda _e, w=self.custom_speed_entry: w.configure(border_color=BORDER), add="+"
        )
        self.custom_speed_entry.bind("<KeyRelease>", self._on_custom_speed_typed)
        self.custom_speed_entry.bind("<FocusOut>", self._on_custom_speed_focus_out)
        self._row(s, 1, "Custom speed (clicks/s)", self.custom_speed_entry, key="custom_speed")

        self.mode_seg = ctk.CTkSegmentedButton(
            s,
            values=list(ACTION_MODES),
            height=34,
            font=ctk.CTkFont(UI_FONT, 13),
            command=lambda _v: self._on_action_mode_change(),
            fg_color=RAISED,
            unselected_color=RAISED,
            unselected_hover_color=BORDER,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            text_color=TEXT,
            text_color_disabled=DIM_TEXT,
        )
        self._row(s, 2, "Action mode", self.mode_seg, key="action_mode")

        self.button_seg = ctk.CTkSegmentedButton(
            s,
            values=list(BUTTON_NAMES),
            height=34,
            font=ctk.CTkFont(UI_FONT, 13),
            command=lambda _v: self._save(),
            fg_color=RAISED,
            unselected_color=RAISED,
            unselected_hover_color=BORDER,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            text_color=TEXT,
            text_color_disabled=DIM_TEXT,
        )
        self._row(s, 3, "Mouse button", self.button_seg, key="button")

        self.interval_entry = self._entry(s)
        self.interval_entry.bind("<KeyRelease>", self._on_interval_typed)
        self.interval_entry.bind("<FocusOut>", lambda _e: self._save())
        self._row(s, 4, "Interval (ms)", self.interval_entry, key="interval")

        self.count_entry = self._entry(s)
        self._row(s, 5, "Clicks (0 = ∞)", self.count_entry)
        self.time_limit_entry = self._entry(s)
        self._row(s, 6, "Stop after (min, 0=∞)", self.time_limit_entry)
        self.double_sw = self._switch(s, command=self._save)
        self._row(s, 7, "Double click", self.double_sw, key="double")
        self.jitter_sw = self._switch(s, command=self._on_jitter_toggle)
        self._row(s, 8, "Random extra delay", self.jitter_sw, key="jitter_on")
        self.jitter_entry = self._entry(s)
        self._row(s, 9, "Up to (ms)", self.jitter_entry, last=True, key="jitter")

    def _build_options(self, page):
        c = self._card(page, 0, (0, 10))
        c.grid_columnconfigure(1, weight=1)
        self.hotkey_btn = ctk.CTkButton(
            c,
            text="",
            width=130,
            height=34,
            fg_color=RAISED,
            hover_color=BORDER,
            text_color=TEXT,
            text_color_disabled=DIM_TEXT,
            font=ctk.CTkFont(MONO_FONT, 14, "bold"),
            command=self._begin_capture,
        )
        self._row(c, 0, "Start / stop key", self.hotkey_btn)
        self.delay_entry = self._entry(c)
        self._row(c, 1, "Start delay (s)", self.delay_entry)
        self.sound_sw = self._switch(c, command=self._save)
        self._row(c, 2, "Start / stop sound", self.sound_sw)
        self.topmost_sw = self._switch(c, command=self._on_topmost)
        self._row(c, 3, "Always on top", self.topmost_sw)
        self.failsafe_sw = self._switch(c, command=self._save)
        self._row(c, 4, "Corner safety stop", self.failsafe_sw)
        self.tray_sw = self._switch(c, command=self._save)
        self._row(c, 5, "Minimize to system tray", self.tray_sw, last=True)

        # Macro / Location card
        mcard = self._card(page, 1, (0, 10))
        mcard.grid_columnconfigure(1, weight=1)
        self.loc_mode_seg = ctk.CTkSegmentedButton(
            mcard,
            values=list(LOCATION_MODES),
            height=32,
            font=ctk.CTkFont(UI_FONT, 12),
            command=lambda _v: self._save(),
            fg_color=RAISED,
            unselected_color=RAISED,
            unselected_hover_color=BORDER,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            text_color=TEXT,
        )
        self._row(mcard, 0, "Target location", self.loc_mode_seg)

        macro_btns = ctk.CTkFrame(mcard, fg_color="transparent")
        self.record_pos_btn = ctk.CTkButton(
            macro_btns,
            text="Record Pos (F8)",
            width=120,
            height=30,
            fg_color=RAISED,
            hover_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(UI_FONT, 12),
            command=self._record_cursor_point,
        )
        self.record_pos_btn.grid(row=0, column=0, padx=(0, 6))
        self.clear_pos_btn = ctk.CTkButton(
            macro_btns,
            text="Clear",
            width=64,
            height=30,
            fg_color=RAISED,
            hover_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(UI_FONT, 12),
            command=self._clear_cursor_points,
        )
        self.clear_pos_btn.grid(row=0, column=1)
        self._row(mcard, 1, "Macro points", macro_btns, last=True)

        self.opt_note = ctk.CTkLabel(
            page,
            text_color=MUTED,
            justify="left",
            anchor="w",
            wraplength=430,
            font=ctk.CTkFont(UI_FONT, 12),
            text=(
                "Click the key box, then press the new key. Esc cancels.\n"
                "Switching presets never changes your Start / stop key.\n"
                "Press F8 anywhere to record the current cursor position for Fixed / Sequence mode."
            ),
        )
        self.opt_note.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        btn_row = ctk.CTkFrame(page, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        self.reset_btn = ctk.CTkButton(
            btn_row,
            text="Reset to defaults",
            height=34,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER,
            hover_color=RAISED,
            text_color=TEXT,
            text_color_disabled=DIM_TEXT,
            font=ctk.CTkFont(UI_FONT, 13),
            command=self._reset_defaults,
        )
        self.reset_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.update_btn = ctk.CTkButton(
            btn_row,
            text="Check for updates",
            height=34,
            fg_color=RAISED,
            hover_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(UI_FONT, 13),
            command=self._check_updates_async,
        )
        self.update_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _card(self, parent, row, pady):
        f = ctk.CTkFrame(
            parent, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER
        )
        f.grid(row=row, column=0, sticky="ew", pady=pady)
        return f

    def _row(self, parent, r, label, widget, last=False, key=None):
        top = 12 if r == 0 else 4
        bottom = 12 if last else 4
        lab = ctk.CTkLabel(
            parent, text=label, text_color=TEXT, anchor="w", font=ctk.CTkFont(UI_FONT, 14)
        )
        lab.grid(row=r, column=0, sticky="w", padx=(16, 8), pady=(top, bottom))
        widget.grid(row=r, column=1, sticky="e", padx=(8, 16), pady=(top, bottom))
        if key:
            self.row_labels[key] = lab

    def _entry(self, parent):
        e = ctk.CTkEntry(
            parent,
            width=96,
            height=34,
            justify="center",
            fg_color=RAISED,
            border_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(MONO_FONT, 14),
            validate="key",
            validatecommand=self._digits,
        )
        e.bind("<Key>", lambda _e, w=e: w.configure(border_color=BORDER), add="+")
        return e

    def _switch(self, parent, command=None):
        return ctk.CTkSwitch(
            parent,
            text="",
            width=46,
            command=command,
            progress_color=ACCENT,
            fg_color=RAISED,
            button_color=TEXT,
            button_hover_color="#FFFFFF",
        )

    # ───────── greyed-out styling ─────────
    @staticmethod
    def _dim_entry(w, dim):
        w.configure(
            fg_color=DIM_BG if dim else RAISED,
            text_color=DIM_TEXT if dim else TEXT,
            border_color=DIM_BORDER if dim else BORDER,
        )

    @staticmethod
    def _dim_switch(w, dim):
        w.configure(
            progress_color=DIM_SEL if dim else ACCENT,
            fg_color=DIM_BG if dim else RAISED,
            button_color=DIM_TEXT if dim else TEXT,
            button_hover_color=DIM_TEXT if dim else "#FFFFFF",
        )

    @staticmethod
    def _dim_seg(w, dim):
        w.configure(
            selected_color=DIM_SEL if dim else ACCENT,
            selected_hover_color=DIM_SEL if dim else ACCENT_HOVER,
            unselected_color=DIM_BG if dim else RAISED,
            unselected_hover_color=DIM_BG if dim else BORDER,
            fg_color=DIM_BG if dim else RAISED,
            text_color=DIM_TEXT if dim else TEXT,
        )

    @staticmethod
    def _dim_menu(w, dim):
        w.configure(
            fg_color=DIM_BG if dim else RAISED,
            button_color=DIM_SEL if dim else BORDER,
            text_color=DIM_TEXT if dim else TEXT,
        )

    def _refresh_states(self):
        """Single place that decides what is editable and how it looks."""
        idle = not self.session_active
        mc = bool(self.mc_sw.get())
        hold = self.mode_seg.get() == "Hold" and not mc
        jitter_on = bool(self.jitter_sw.get())
        free = idle and not mc
        is_default_preset = self.preset_seg.get() == "Default"

        def state(ok):
            return "normal" if ok else "disabled"

        self._dim_seg(self.mode_seg, mc)
        self.mode_seg.configure(state=state(free))

        self._dim_seg(self.button_seg, mc)
        self.button_seg.configure(state=state(free))

        interval_dim = mc or hold
        self._dim_entry(self.interval_entry, interval_dim)
        self.interval_entry.configure(state=state(free and not hold))

        self._dim_switch(self.double_sw, interval_dim)
        self.double_sw.configure(state=state(free and not hold))

        self._dim_switch(self.jitter_sw, interval_dim)
        self.jitter_sw.configure(state=state(free and not hold))

        jitter_ok = free and not hold and jitter_on
        self._dim_entry(self.jitter_entry, interval_dim or not jitter_on)
        self.jitter_entry.configure(state=state(jitter_ok))

        # Custom speed (clicks/s) is editable in Default/manual Click mode AND in MC "Custom speed" weapon mode
        custom_speed_editable = idle and (
            (not mc and not hold) or (mc and self.weapon_menu.get() == "Custom speed")
        )
        self._dim_entry(self.custom_speed_entry, not custom_speed_editable)
        self.custom_speed_entry.configure(state=state(custom_speed_editable))

        for key, dim in (
            ("action_mode", mc),
            ("button", mc),
            ("interval", interval_dim),
            ("double", interval_dim),
            ("jitter_on", interval_dim),
            ("jitter", interval_dim or not jitter_on),
            ("custom_speed", not custom_speed_editable),
        ):
            if key in self.row_labels:
                self.row_labels[key].configure(text_color=DIM_TEXT if dim else TEXT)

        self._dim_menu(self.weapon_menu, not mc)
        self.weapon_menu.configure(state=state(idle and mc))
        self.mc_sw.configure(state=state(idle))
        self.preset_seg.configure(state=state(idle))

        # Save Default button is enabled only when in Default mode and idle
        can_save_default = idle and is_default_preset
        self.save_preset_btn.configure(
            state=state(can_save_default),
            fg_color=ACCENT if can_save_default else DIM_BG,
        )

        for w in (
            self.count_entry,
            self.time_limit_entry,
            self.delay_entry,
            self.hotkey_btn,
            self.reset_btn,
        ):
            w.configure(state=state(idle))

    # ───────── live CPS <-> Interval (ms) sync ─────────
    def _on_custom_speed_typed(self, _event=None):
        if self._syncing_fields or self.session_active:
            return
        raw = self.custom_speed_entry.get().strip()
        if not raw:
            return
        try:
            val = float(raw)
        except ValueError:
            return
        if val <= 0:
            return

        self._syncing_fields = True
        try:
            if self.mc_sw.get():
                if self.weapon_menu.get() == "Custom speed":
                    spd = min(max(val, 0.1), 20.0)
                    self._put(self.interval_entry, mc_interval(spd))
            else:
                cps = min(max(val, MIN_CPS), MAX_CPS)
                ms = cps_to_interval_ms(cps)
                self._put(self.interval_entry, ms)
                self._manual["interval"] = ms
                self._manual["custom_cps"] = round(cps, 2)
        finally:
            self._syncing_fields = False
        self._refresh_states()

    def _on_custom_speed_focus_out(self, _event=None):
        self._on_custom_speed_typed()
        self._save()

    def _on_interval_typed(self, _event=None):
        if self._syncing_fields or self.session_active or self.mc_sw.get():
            return
        raw = self.interval_entry.get().strip()
        if not raw or not raw.isdigit():
            return
        ms = int(raw)
        if ms < MIN_INTERVAL:
            return
        self._syncing_fields = True
        try:
            cps = interval_ms_to_cps(min(ms, MAX_MS))
            self._put(self.custom_speed_entry, cps)
            self._manual["interval"] = min(ms, MAX_MS)
            self._manual["custom_cps"] = cps
        finally:
            self._syncing_fields = False
        self._refresh_states()

    def _on_action_mode_change(self):
        self._refresh_states()
        self._refresh_hotkey_labels()
        self._save()

    def _on_jitter_toggle(self):
        self._refresh_states()
        self._save()

    # ───────── settings <-> widgets ─────────
    def _put(self, entry, value):
        prev_state = entry.cget("state")
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, str(value))
        if prev_state == "disabled":
            entry.configure(state="disabled")

    @staticmethod
    def _set_switch(sw, on):
        sw.select() if on else sw.deselect()

    def _write_manual(self, m):
        self.mode_seg.set(m.get("action_mode", "Click"))
        self.button_seg.set(m["button"])
        self._put(self.interval_entry, m["interval"])
        cps_val = m.get("custom_cps") or interval_ms_to_cps(m["interval"])
        self._put(self.custom_speed_entry, cps_val)
        self._put(self.jitter_entry, m["jitter"])
        self._set_switch(self.double_sw, m["double"])
        self._set_switch(self.jitter_sw, m["jitter_on"])

    def _mc_spd(self):
        w = self.weapon_menu.get()
        if w == "Custom speed":
            raw = self.custom_speed_entry.get().strip()
            try:
                return min(max(float(raw), 0.1), 20.0)
            except ValueError:
                return float(self.settings.get("mc_custom_speed", 1.6))
        return WEAPONS.get(w, WEAPONS["Sword"])

    def _mc_ms(self):
        return mc_interval(self._mc_spd())

    def _write_mc(self):
        """Show the values Minecraft mode forces."""
        self.mode_seg.set("Click")
        self.button_seg.set("Left")
        spd = self._mc_spd()
        self._put(self.custom_speed_entry, spd)
        self._put(self.interval_entry, mc_interval(spd))
        self._set_switch(self.double_sw, False)
        self._set_switch(self.jitter_sw, False)

    def _snapshot_manual(self):
        """Read the manual widgets leniently, keeping old values where the field is invalid."""
        m = dict(self._manual)
        m["action_mode"] = self.mode_seg.get()
        m["button"] = self.button_seg.get()
        m["double"] = bool(self.double_sw.get())
        m["jitter_on"] = bool(self.jitter_sw.get())
        for key, entry, lo in (
            ("interval", self.interval_entry, MIN_INTERVAL),
            ("jitter", self.jitter_entry, 0),
        ):
            raw = entry.get().strip()
            if raw.isdigit():
                m[key] = min(max(int(raw), lo), MAX_MS)
        raw_cps = self.custom_speed_entry.get().strip()
        try:
            val_cps = float(raw_cps)
            if MIN_CPS <= val_cps <= MAX_CPS:
                m["custom_cps"] = round(val_cps, 2)
        except ValueError:
            pass
        return m

    def _apply(self, cfg):
        self._manual = {k: cfg.get(k, DEFAULTS[k]) for k in MANUAL_KEYS}
        self._write_manual(self._manual)
        self._put(self.count_entry, cfg["clicks"])
        self._put(self.time_limit_entry, cfg.get("time_limit_min", 0))
        self._put(self.delay_entry, cfg["start_delay"])
        self.weapon_menu.set(cfg["mc_weapon"])
        self.loc_mode_seg.set(cfg.get("location_mode", "Cursor"))
        preset_name = cfg.get("active_preset", "Default")
        if preset_name not in PRESET_MODES:
            preset_name = "Default"
        self.preset_seg.set(preset_name)
        for sw, on in (
            (self.mc_sw, cfg["mc_mode"]),
            (self.sound_sw, cfg.get("sound_on", True)),
            (self.topmost_sw, cfg["topmost"]),
            (self.failsafe_sw, cfg["failsafe"]),
            (self.tray_sw, cfg.get("minimize_to_tray", False)),
        ):
            self._set_switch(sw, on)
        if cfg["mc_mode"]:
            if cfg["mc_weapon"] == "Custom speed":
                self._put(self.custom_speed_entry, cfg.get("mc_custom_speed", 1.6))
            self._write_mc()
        self.hotkey_id = cfg["hotkey"]
        self.record_key_id = cfg.get("record_key", "f8")
        if self.record_key_id == self.hotkey_id:
            self.record_key_id = "f8" if self.hotkey_id != "f8" else "f7"
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

    def _float_num(self, entry, label, lo, hi, page="main"):
        raw = entry.get().strip()
        try:
            value = float(raw)
        except ValueError:
            raise ConfigError(f"{label} must be a valid number.", entry, page)
        if not lo <= value <= hi:
            raise ConfigError(f"{label} must be between {lo} and {hi}.", entry, page)
        return value

    def _collect(self):
        mc = bool(self.mc_sw.get())
        custom_mc_spd = self.settings.get("mc_custom_speed", 1.6)
        if mc:
            if self.weapon_menu.get() == "Custom speed":
                custom_mc_spd = self._float_num(
                    self.custom_speed_entry, "Custom speed", 0.1, 20.0
                )
            manual = dict(self._manual)
        else:
            mode = self.mode_seg.get()
            if mode == "Hold":
                interval_val = self._manual["interval"]
                custom_cps_val = self._manual.get(
                    "custom_cps", interval_ms_to_cps(interval_val)
                )
            else:
                custom_cps_val = self._float_num(
                    self.custom_speed_entry, "Custom speed (clicks/s)", MIN_CPS, MAX_CPS
                )
                interval_val = self._num(self.interval_entry, "Interval", MIN_INTERVAL, MAX_MS)
            manual = {
                "action_mode": mode,
                "button": self.button_seg.get(),
                "interval": interval_val,
                "custom_cps": round(custom_cps_val, 2),
                "double": bool(self.double_sw.get()),
                "jitter_on": bool(self.jitter_sw.get()),
                "jitter": self._manual["jitter"],
            }
            if manual["jitter_on"] and mode != "Hold":
                manual["jitter"] = self._num(
                    self.jitter_entry, "Random delay", 0, MAX_MS, empty=0
                )
        cfg = {
            **self.settings,
            **manual,
            "clicks": self._num(self.count_entry, "Click count", 0, MAX_CLICKS, empty=0),
            "time_limit_min": self._num(
                self.time_limit_entry, "Time limit", 0, MAX_MINUTES, empty=0
            ),
            "hotkey": self.hotkey_id,
            "record_key": self.record_key_id,
            "sound_on": bool(self.sound_sw.get()),
            "topmost": bool(self.topmost_sw.get()),
            "failsafe": bool(self.failsafe_sw.get()),
            "minimize_to_tray": bool(self.tray_sw.get()),
            "location_mode": self.loc_mode_seg.get(),
            "start_delay": self._num(
                self.delay_entry, "Start delay", 0, MAX_DELAY, empty=0, page="options"
            ),
            "mc_mode": mc,
            "mc_weapon": self.weapon_menu.get(),
            "mc_custom_speed": custom_mc_spd,
            "active_preset": self.preset_seg.get(),
        }
        self._manual = manual
        return cfg

    def _save(self):
        try:
            self.settings = self._collect()
        except ConfigError:
            self.settings = {
                **self.settings,
                **self._manual,
                "hotkey": self.hotkey_id,
                "record_key": self.record_key_id,
                "sound_on": bool(self.sound_sw.get()),
                "topmost": bool(self.topmost_sw.get()),
                "failsafe": bool(self.failsafe_sw.get()),
                "minimize_to_tray": bool(self.tray_sw.get()),
                "location_mode": self.loc_mode_seg.get(),
                "mc_mode": bool(self.mc_sw.get()),
                "mc_weapon": self.weapon_menu.get(),
                "active_preset": self.preset_seg.get(),
            }
        # If the user is in Default mode, automatically keep the Default preset synced with their settings
        if self.settings.get("active_preset") == "Default" and not self.settings.get("mc_mode"):
            self.presets["Default"] = dict(self.settings)
            save_presets(self.presets)
        save_settings(self.settings)

    # ───────── 2-Mode Presets (Default vs Sword) ─────────
    def _on_preset_select(self, name):
        if self.session_active or name not in PRESET_MODES:
            return
        # Save current manual settings into Default before switching to Sword
        if name == "Sword (Minecraft)" and not self.mc_sw.get():
            try:
                current_cfg = self._collect()
                current_cfg["active_preset"] = "Default"
                self.presets["Default"] = dict(current_cfg)
                save_presets(self.presets)
            except ConfigError:
                pass

        target_preset = self.presets.get(name, DEFAULTS)
        # Merge preset without EVER changing hotkey or global user preferences
        merged = merge_preset_preserving_globals(self.settings, target_preset)
        merged["active_preset"] = name
        self.settings = merged
        self._apply(self.settings)
        save_settings(self.settings)
        self._say(f"Mode: {name} (Start/stop key {key_label(self.hotkey_id)} unchanged)", OK_TEXT)

    def _save_default_preset(self):
        if self.session_active:
            return
        try:
            cfg = self._collect()
        except ConfigError as err:
            self._show_error(err)
            return
        cfg["active_preset"] = "Default"
        self.preset_seg.set("Default")
        self.presets["Default"] = dict(cfg)
        save_presets(self.presets)
        save_settings(cfg)
        self._refresh_states()
        self._say("Saved your current settings to Default preset.", OK_TEXT)

    # ───────── Macro positions ─────────
    def _record_cursor_point(self):
        try:
            x, y = mouse.Controller().position
        except (OSError, RuntimeError, AttributeError):
            x, y = self.winfo_pointerxy()
        x, y = int(x), int(y)
        self.settings["fixed_x"] = x
        self.settings["fixed_y"] = y
        pts = list(self.settings.get("sequence_points") or [])
        pts.append([x, y])
        self.settings["sequence_points"] = pts
        save_settings(self.settings)
        msg = f"Recorded ({x}, {y}) · Sequence has {len(pts)} point(s)."
        self._say(msg, OK_TEXT)
        self._opt_say(msg, OK_TEXT)

    def _clear_cursor_points(self):
        self.settings["sequence_points"] = []
        save_settings(self.settings)
        self._opt_say("Cleared recorded macro sequence points.", OK_TEXT)

    def _reset_defaults(self):
        if self.session_active:
            return
        self._end_capture()
        reset_cfg = dict(DEFAULTS)
        self.presets["Default"] = dict(reset_cfg)
        save_presets(self.presets)
        self._apply(reset_cfg)
        self._save()
        self._opt_say("Settings restored to factory defaults.", OK_TEXT)

    def _on_topmost(self, save=True):
        self.attributes("-topmost", bool(self.topmost_sw.get()))
        if save:
            self._save()

    # ───────── Minecraft mode ─────────
    def _on_mc_toggle(self):
        if self.mc_sw.get():
            self._manual = self._snapshot_manual()
            if self.weapon_menu.get() == "Custom speed":
                self._put(self.custom_speed_entry, self.settings.get("mc_custom_speed", 1.6))
            self._write_mc()
            if self.weapon_menu.get() == "Sword":
                self.preset_seg.set("Sword (Minecraft)")
        else:
            self.preset_seg.set("Default")
            self._write_manual(self._manual)
        self._refresh_states()
        self._refresh_hotkey_labels()
        self._save()

    def _on_weapon(self, _value=None):
        if self.mc_sw.get():
            if self.weapon_menu.get() == "Custom speed":
                self._put(self.custom_speed_entry, self.settings.get("mc_custom_speed", 1.6))
            self._write_mc()
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
            self._say(
                f"Minecraft mode — a full-charge hit every {self._mc_ms()} ms. "
                f"Aim, then press {key}"
            )
        elif self.mode_seg.get() == "Hold":
            self._say(f"Hold mode — holds mouse button continuously. Press {key} to start")
        else:
            cps = self.custom_speed_entry.get().strip() or "10.0"
            self._say(f"Ready ({cps} clicks/s) — move cursor to target, then press {key}")
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
        rec_label = key_label(self.record_key_id)
        if not self.capturing:
            self.hotkey_btn.configure(text=label)
        self.record_pos_btn.configure(text=f"Record Pos ({rec_label})")
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
        self.hotkey_btn.configure(
            text="Press a key…", fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF"
        )
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
            if self.record_key_id == kid:
                self.record_key_id = "f8" if kid != "f8" else "f7"
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

        if cfg.get("location_mode") == "Sequence" and not cfg.get("sequence_points"):
            self._say("No sequence points recorded yet — clicking at current cursor.", MUTED)

        self.settings = cfg
        self._save()
        run_cfg = effective(cfg)
        self._fast = run_cfg["interval"] < 10 and run_cfg.get("action_mode") != "Hold"
        self._run_interval = run_cfg["interval"]
        self._run_mc = cfg["mc_mode"]
        self._run_hold = run_cfg.get("action_mode") == "Hold"
        self.session_active = True
        self._refresh_states()
        self.main_btn.configure(
            text=f"Stop  ·  {key_label(self.hotkey_id)}", fg_color=STOP, hover_color=STOP_HOVER
        )
        self.engine.start(run_cfg, cfg["start_delay"] if from_button else 0)

    def _finish(self):
        self.session_active = False
        self._refresh_states()
        self.main_btn.configure(
            text=f"Start  ·  {key_label(self.hotkey_id)}",
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        n, why = self.engine.count, self.engine.reason
        telem = self.engine.format_telemetry()
        if telem:
            self.telemetry_label.configure(text=telem, text_color=TEXT)
        if why == "error":
            self._say(f"Couldn't click: {self.engine.error}", ERR_TEXT)
        elif why == "done":
            self._say(f"Done — {n:,} clicks", OK_TEXT)
        elif why == "time_limit":
            self._say(f"Time limit reached — {n:,} clicks", OK_TEXT)
        elif why == "failsafe":
            self._say(f"Safety stop — cursor reached the corner. {n:,} clicks")
        else:
            self._say(f"Stopped — {n:,} clicks")

    # ───────── main loop (4 Hz UI stats refresh) ─────────
    def _poll(self):
        try:
            while True:
                kind, *payload = self.events.get_nowait()
                if kind == "toggle":
                    self.toggle()
                elif kind == "record_pos":
                    self._record_cursor_point()
                elif kind == "capture":
                    self._handle_capture(payload[0])
                elif kind == "restore_from_tray":
                    self._restore_from_tray()
                elif kind == "quit_from_tray":
                    self._on_close()
                    return
        except queue.Empty:
            pass

        try:
            eng = self.engine
            now_mono = time.monotonic()
            # Throttle UI text updates to 4 times per second (every 250 ms) or when session finishes
            if (now_mono - self._last_stats_update >= self.STATS_INTERVAL_S) or not eng.active:
                self._last_stats_update = now_mono
                if eng.count != self._cache["count"]:
                    self._cache["count"] = eng.count
                    self.count_label.configure(text=f"{eng.count:,}")
                elapsed = eng.elapsed
                rate = eng.count / elapsed if elapsed >= 1 else 0.0
                stats = f"{fmt_time(elapsed)}  ·  {rate:.1f} clicks/s  ·  CPU {eng.cpu_percent:.1f}%"
                if stats != self._cache["stats"]:
                    self._cache["stats"] = stats
                    self.stats_label.configure(text=stats)

            if self.session_active and not eng.active:
                self._finish()
            elif eng.active:
                key = key_label(self.hotkey_id)
                if eng.phase == "countdown":
                    left = max(1, math.ceil(eng.warmup_end - now_mono))
                    self._say(f"Starting in {left} s — move the cursor to your target")
                elif self._run_hold:
                    self._say(f"Holding mouse button — press {key} to release", OK_TEXT)
                elif self._run_mc:
                    self._say(
                        f"Minecraft mode — a hit every {self._run_interval} ms · "
                        f"press {key} to stop",
                        OK_TEXT,
                    )
                elif self._fast:
                    self._say("Running at under 10 ms — some apps may skip clicks", OK_TEXT)
                else:
                    self._say(f"Running — press {key} to stop", OK_TEXT)

            if now_mono - self._last_check > 2:
                self._last_check = now_mono
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
                self._held_key = kid
                self.events.put(("capture", key))
            elif kid == self.hotkey_id and self._held_key != kid:
                self._held_key = kid
                self.events.put(("toggle",))
            elif kid == self.record_key_id and self._held_key != kid and not self.session_active:
                self._held_key = kid
                self.events.put(("record_pos",))

        def on_release(key):
            if key_id(key) == self._held_key:
                self._held_key = None

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.daemon = True
        try:
            self.listener.start()
        except (OSError, RuntimeError):
            log_error(traceback.format_exc())

    # ───────── system tray & update checker ─────────
    def _on_window_close_request(self):
        if bool(self.tray_sw.get()) and pystray is not None and Image is not None:
            self._hide_to_tray()
        else:
            self._on_close()

    def _hide_to_tray(self):
        self.withdraw()
        if self._tray_icon is not None:
            return
        icon_path = get_resource_path("assets/icon.png")
        try:
            img = Image.open(icon_path) if icon_path.exists() else Image.new("RGB", (64, 64), "#4A63D8")
        except (OSError, ValueError):
            img = Image.new("RGB", (64, 64), "#4A63D8")
        menu = pystray.Menu(
            pystray.MenuItem(
                "Open Auto Clicker", lambda: self.events.put(("restore_from_tray",)), default=True
            ),
            pystray.MenuItem("Start / Stop", lambda: self.events.put(("toggle",))),
            pystray.MenuItem("Quit", lambda: self.events.put(("quit_from_tray",))),
        )
        self._tray_icon = pystray.Icon("AutoClicker", img, f"Auto Clicker v{__version__}", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _restore_from_tray(self):
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except (OSError, RuntimeError) as exc:
                log_error(f"Tray stop warning: {exc}")
            self._tray_icon = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def _check_updates_async(self):
        self._opt_say("Checking GitHub for updates…", MUTED)

        def worker():
            url = f"https://api.github.com/repos/{__repo_owner__}/{__repo_name__}/releases/latest"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": f"AutoClicker/{__version__}"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latest = str(data.get("tag_name", "")).lstrip("v")
                default_url = f"https://github.com/{__repo_owner__}/{__repo_name__}/releases"
                html_url = data.get("html_url", default_url)
                if latest and latest != __version__:
                    msg = f"Update v{latest} available! Opening browser…"
                    self.after(0, lambda: self._opt_say(msg, OK_TEXT))
                    webbrowser.open(html_url)
                else:
                    msg = f"You are on the latest version (v{__version__})."
                    self.after(0, lambda: self._opt_say(msg, OK_TEXT))
            except (OSError, ValueError, KeyError):
                self.after(0, lambda: self._opt_say("Could not check updates right now.", ERR_TEXT))

        threading.Thread(target=worker, daemon=True).start()

    # ───────── safety nets ─────────
    def report_callback_exception(self, exc, val, tb):
        log_error("".join(traceback.format_exception(exc, val, tb)))
        self.engine.stop()
        self._say(f"Unexpected error: {val}", ERR_TEXT)

    def _on_close(self):
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except (OSError, RuntimeError) as exc:
                log_error(f"Tray stop warning: {exc}")
            self._tray_icon = None
        self.engine.stop()
        self._save()
        try:
            self.listener.stop()
        except (OSError, RuntimeError) as exc:
            log_error(f"Listener stop warning: {exc}")
        self.destroy()
