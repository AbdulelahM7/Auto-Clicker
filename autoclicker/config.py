"""Configuration, Minecraft weapons/tools data, presets, and validation."""

import json
import math
import os
import re
import sys
import time
from pathlib import Path

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
BUTTON_NAMES = ("Left", "Middle", "Right")
ACTION_MODES = ("Click", "Hold")
LOCATION_MODES = ("Cursor", "Fixed", "Sequence")
PRESET_MODES = ("Default", "Sword (Minecraft)")

MODIFIERS = {
    "shift", "shift_l", "shift_r", "ctrl", "ctrl_l", "ctrl_r",
    "alt", "alt_l", "alt_r", "alt_gr", "cmd", "cmd_l", "cmd_r",
}
MIN_INTERVAL = 1
MAX_MS = 3_600_000          # 1 hour
MIN_CPS = 0.1
MAX_CPS = 1000.0
MAX_CLICKS = 100_000_000
MAX_DELAY = 30              # seconds
MAX_MINUTES = 10_080        # 7 days in minutes
CORNER = 3                  # px: safety-stop zone in the top-left corner

# Minecraft Java: attack speed (attacks per second) of each weapon/tool class.
# Full charge takes 20 / speed game ticks (1 tick = 50 ms).
WEAPONS = {
    "Sword": 1.6,
    "Axe: wood/stone/copper": 0.8,
    "Axe: iron": 0.9,
    "Axe: gold/diamond/netherite": 1.0,
    "Pickaxe": 1.2,
    "Shovel": 1.0,
    "Hoe: wood/gold/copper": 1.0,
    "Hoe: stone": 2.0,
    "Hoe: iron": 3.0,
    "Hoe: diamond/netherite": 4.0,
    "Trident": 1.1,
    "Spear": 1.2,
    "Mace": 0.6,
    "Fist": 4.0,
    "Custom speed": 0.0,
}
TICK_MS = 50
MC_MARGIN_MS = 10           # small safety margin so a hit never lands a hair early


def mc_interval(speed):
    """Milliseconds between hits for a fully charged Minecraft attack."""
    if speed <= 0:
        raise ValueError("Attack speed must be greater than 0.")
    return math.ceil(20 / speed - 1e-9) * TICK_MS + MC_MARGIN_MS


def cps_to_interval_ms(cps):
    """Convert clicks per second (CPS) to interval in milliseconds."""
    if cps <= 0:
        raise ValueError("Clicks per second (CPS) must be greater than 0.")
    ms = round(1000.0 / float(cps))
    return min(max(int(ms), MIN_INTERVAL), MAX_MS)


def interval_ms_to_cps(interval_ms):
    """Convert interval in milliseconds to clicks per second (CPS)."""
    if interval_ms <= 0:
        raise ValueError("Interval must be greater than 0.")
    return round(1000.0 / float(interval_ms), 2)


DEFAULTS = {
    "action_mode": "Click",
    "button": "Left",
    "interval": 100,
    "custom_cps": 10.0,
    "clicks": 0,
    "time_limit_min": 0,
    "double": False,
    "jitter_on": False,
    "jitter": 50,
    "hotkey": "f6",
    "record_key": "f8",
    "topmost": False,
    "failsafe": True,
    "sound_on": True,
    "minimize_to_tray": False,
    "start_delay": 3,
    "mc_mode": False,
    "mc_weapon": "Sword",
    "mc_custom_speed": 1.6,
    "location_mode": "Cursor",
    "fixed_x": 0,
    "fixed_y": 0,
    "sequence_points": [],
    "active_preset": "Default",
}
MANUAL_KEYS = ("action_mode", "button", "interval", "custom_cps", "double", "jitter_on", "jitter")

# Keys that belong to the user's global preferences and must NEVER be overwritten when switching presets
GLOBAL_OPTION_KEYS = (
    "hotkey",
    "record_key",
    "start_delay",
    "sound_on",
    "topmost",
    "failsafe",
    "minimize_to_tray",
    "location_mode",
    "fixed_x",
    "fixed_y",
    "sequence_points",
)

BUILTIN_PRESETS = {
    "Default": dict(DEFAULTS),
    "Sword (Minecraft)": {
        **DEFAULTS,
        "action_mode": "Click",
        "button": "Left",
        "mc_mode": True,
        "mc_weapon": "Sword",
        "interval": mc_interval(WEAPONS["Sword"]),
        "double": False,
        "jitter_on": False,
        "jitter": 0,
        "active_preset": "Sword (Minecraft)",
    },
}

CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "AutoClicker"
CONFIG_PATH = CONFIG_DIR / "settings.json"
PRESETS_PATH = CONFIG_DIR / "presets.json"
LOG_PATH = CONFIG_DIR / "error.log"


def get_resource_path(relative_path):
    """Resolve asset path both in normal Python execution and inside PyInstaller onefile/onedir bundles."""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_dir / relative_path


def sanitize_settings(data):
    """Validate and clamp a dictionary of settings against DEFAULTS."""
    cfg = dict(DEFAULTS)
    if isinstance(data, dict):
        for key, default in DEFAULTS.items():
            value = data.get(key, default)
            if isinstance(default, bool):
                cfg[key] = value if isinstance(value, bool) else default
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
                cfg[key] = value if ok else default
            elif isinstance(default, float):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                cfg[key] = float(value) if ok else default
            elif isinstance(default, list):
                if isinstance(value, list):
                    pts = []
                    for item in value:
                        if (
                            isinstance(item, (list, tuple))
                            and len(item) == 2
                            and all(isinstance(c, int) and not isinstance(c, bool) for c in item)
                        ):
                            pts.append([item[0], item[1]])
                    cfg[key] = pts
                else:
                    cfg[key] = list(default)
            else:
                cfg[key] = value if isinstance(value, str) else default

    if cfg["action_mode"] not in ACTION_MODES:
        cfg["action_mode"] = DEFAULTS["action_mode"]
    if cfg["button"] not in BUTTON_NAMES:
        cfg["button"] = DEFAULTS["button"]
    if cfg["mc_weapon"] not in WEAPONS:
        cfg["mc_weapon"] = DEFAULTS["mc_weapon"]
    if cfg["location_mode"] not in LOCATION_MODES:
        cfg["location_mode"] = DEFAULTS["location_mode"]
    if cfg["active_preset"] not in PRESET_MODES:
        cfg["active_preset"] = DEFAULTS["active_preset"]

    cfg["interval"] = min(max(cfg["interval"], MIN_INTERVAL), MAX_MS)
    cfg["custom_cps"] = round(min(max(float(cfg["custom_cps"]), MIN_CPS), MAX_CPS), 2)
    cfg["clicks"] = min(max(cfg["clicks"], 0), MAX_CLICKS)
    cfg["time_limit_min"] = min(max(cfg["time_limit_min"], 0), MAX_MINUTES)
    cfg["jitter"] = min(max(cfg["jitter"], 0), MAX_MS)
    cfg["start_delay"] = min(max(cfg["start_delay"], 0), MAX_DELAY)
    cfg["mc_custom_speed"] = round(min(max(float(cfg["mc_custom_speed"]), 0.1), 20.0), 2)

    if not cfg["hotkey"] or cfg["hotkey"] in MODIFIERS:
        cfg["hotkey"] = DEFAULTS["hotkey"]
    if not cfg["record_key"] or cfg["record_key"] in MODIFIERS:
        cfg["record_key"] = DEFAULTS["record_key"]
    if cfg["record_key"] == cfg["hotkey"]:
        cfg["record_key"] = "f8" if cfg["hotkey"] != "f8" else "f7"
    return cfg


def merge_preset_preserving_globals(current_cfg, preset_cfg):
    """Apply a preset while strictly preserving start/stop hotkey and global user options."""
    merged = sanitize_settings(preset_cfg)
    for key in GLOBAL_OPTION_KEYS:
        if key in current_cfg:
            merged[key] = current_cfg[key]
    return sanitize_settings(merged)


def load_settings(path=CONFIG_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return sanitize_settings(data)


def save_settings(cfg, path=CONFIG_PATH):
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def load_presets(path=PRESETS_PATH):
    """Load the two modes: customizable 'Default' and fixed 'Sword (Minecraft)'."""
    presets = {
        "Default": sanitize_settings(BUILTIN_PRESETS["Default"]),
        "Sword (Minecraft)": sanitize_settings(BUILTIN_PRESETS["Sword (Minecraft)"]),
    }
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("Default"), dict):
            user_default = sanitize_settings(raw["Default"])
            user_default["active_preset"] = "Default"
            presets["Default"] = user_default
    except (OSError, ValueError):
        pass
    return presets


def save_presets(presets, path=PRESETS_PATH):
    """Persist the user's saved 'Default' preset so it is remembered across restarts."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Default": sanitize_settings(presets.get("Default", DEFAULTS)),
        }
        payload["Default"]["active_preset"] = "Default"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def log_error(text):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
    except OSError:
        pass


def resolve_mc_speed(cfg):
    weapon = cfg.get("mc_weapon", "Sword")
    if weapon == "Custom speed":
        return max(0.1, float(cfg.get("mc_custom_speed", 1.6)))
    return WEAPONS.get(weapon, WEAPONS["Sword"])


def effective(cfg):
    """The settings the engine actually uses (Minecraft mode overrides the manual ones)."""
    if not cfg.get("mc_mode"):
        return dict(cfg)
    speed = resolve_mc_speed(cfg)
    return {
        **cfg,
        "action_mode": "Click",
        "button": "Left",
        "interval": mc_interval(speed),
        "double": False,
        "jitter_on": False,
        "jitter": 0,
    }


def key_label(kid):
    if kid.startswith("vk"):
        return f"Key {kid[2:]}"
    if re.fullmatch(r"f\d+", kid) or len(kid) == 1:
        return kid.upper()
    return kid.replace("_", " ").title()


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
