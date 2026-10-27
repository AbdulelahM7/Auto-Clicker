"""Unit tests for interval calculations, settings loading/validation, presets, and engine telemetry."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker import __version__
from autoclicker.config import (
    DEFAULTS,
    WEAPONS,
    effective,
    fmt_time,
    key_label,
    load_presets,
    load_settings,
    mc_interval,
    sanitize_settings,
    save_presets,
    save_settings,
)
from autoclicker.engine import ClickEngine


class DummyMouse:
    def __init__(self):
        self.position = (200, 200)
        self.clicks = 0
        self.holding = False

    def click(self, button, count=1):
        self.clicks += count

    def press(self, button):
        self.holding = True

    def release(self, button):
        self.holding = False


class TestAutoClickerLogic(unittest.TestCase):
    def test_version_single_source(self):
        self.assertEqual(__version__, "1.0.1")

    def test_minecraft_weapon_intervals(self):
        self.assertEqual(mc_interval(WEAPONS["Sword"]), 660)
        self.assertEqual(mc_interval(WEAPONS["Axe: wood/stone/copper"]), 1260)
        self.assertEqual(mc_interval(WEAPONS["Axe: iron"]), 1160)
        self.assertEqual(mc_interval(WEAPONS["Axe: gold/diamond/netherite"]), 1010)
        self.assertEqual(mc_interval(WEAPONS["Pickaxe"]), 860)
        self.assertEqual(mc_interval(WEAPONS["Shovel"]), 1010)
        self.assertEqual(mc_interval(WEAPONS["Hoe: stone"]), 510)
        self.assertEqual(mc_interval(WEAPONS["Hoe: iron"]), 360)
        self.assertEqual(mc_interval(WEAPONS["Hoe: diamond/netherite"]), 260)
        self.assertEqual(mc_interval(WEAPONS["Trident"]), 960)
        self.assertEqual(mc_interval(WEAPONS["Spear"]), 860)
        self.assertEqual(mc_interval(WEAPONS["Mace"]), 1710)
        self.assertEqual(mc_interval(WEAPONS["Fist"]), 260)

    def test_mc_interval_invalid_speed(self):
        with self.assertRaises(ValueError):
            mc_interval(0)
        with self.assertRaises(ValueError):
            mc_interval(-2.0)

    def test_effective_settings_in_mc_mode(self):
        cfg = {**DEFAULTS, "mc_mode": True, "mc_weapon": "Pickaxe", "button": "Right", "double": True}
        eff = effective(cfg)
        self.assertEqual(eff["button"], "Left")
        self.assertEqual(eff["action_mode"], "Click")
        self.assertEqual(eff["interval"], 860)
        self.assertFalse(eff["double"])
        self.assertFalse(eff["jitter_on"])

    def test_effective_custom_attack_speed(self):
        cfg = {**DEFAULTS, "mc_mode": True, "mc_weapon": "Custom speed", "mc_custom_speed": 2.5}
        eff = effective(cfg)
        self.assertEqual(eff["interval"], 410)

    def test_sanitize_and_clamp_settings(self):
        corrupted = {
            "action_mode": "InvalidMode",
            "button": "InvalidBtn",
            "interval": -50,
            "clicks": -10,
            "time_limit_min": 999999,
            "hotkey": "ctrl_l",
            "mc_custom_speed": -5,
            "sequence_points": [[100, 200], "bad_point", [10]],
        }
        clean = sanitize_settings(corrupted)
        self.assertEqual(clean["action_mode"], "Click")
        self.assertEqual(clean["button"], "Left")
        self.assertEqual(clean["interval"], 1)
        self.assertEqual(clean["clicks"], 0)
        self.assertEqual(clean["time_limit_min"], 10080)
        self.assertEqual(clean["hotkey"], "f6")
        self.assertEqual(clean["mc_custom_speed"], 0.1)
        self.assertEqual(clean["sequence_points"], [[100, 200]])

    def test_save_and_load_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            custom = {**DEFAULTS, "interval": 250, "action_mode": "Hold", "button": "Right"}
            save_settings(custom, path=p)
            loaded = load_settings(path=p)
            self.assertEqual(loaded["interval"], 250)
            self.assertEqual(loaded["action_mode"], "Hold")
            self.assertEqual(loaded["button"], "Right")

    def test_presets_load_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "presets.json"
            presets = load_presets(path=p)
            self.assertIn("Sword (Minecraft)", presets)
            presets["My Farm"] = {**DEFAULTS, "interval": 500, "active_preset": "My Farm"}
            save_presets(presets, path=p)
            reloaded = load_presets(path=p)
            self.assertIn("My Farm", reloaded)
            self.assertEqual(reloaded["My Farm"]["interval"], 500)

    def test_engine_click_and_telemetry(self):
        dummy = DummyMouse()
        eng = ClickEngine(controller_factory=lambda: dummy)
        cfg = {**DEFAULTS, "interval": 20, "clicks": 4, "sound_on": False, "failsafe": False}
        eng.start(cfg, warmup_s=0)
        deadline = time.time() + 2.0
        while eng.active and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(eng.count, 4)
        self.assertEqual(eng.reason, "done")
        self.assertGreater(eng.avg_interval_ms, 10.0)
        self.assertIn("ms avg", eng.format_telemetry())

    def test_engine_hold_mode(self):
        dummy = DummyMouse()
        eng = ClickEngine(controller_factory=lambda: dummy)
        cfg = {**DEFAULTS, "action_mode": "Hold", "sound_on": False, "failsafe": False}
        eng.start(cfg, warmup_s=0)
        time.sleep(0.08)
        eng.stop()
        while eng.active:
            time.sleep(0.01)
        self.assertEqual(eng.count, 1)
        self.assertFalse(dummy.holding)
        self.assertEqual(eng.reason, "stopped")

    def test_helpers(self):
        self.assertEqual(key_label("f6"), "F6")
        self.assertEqual(key_label("vk65"), "Key 65")
        self.assertEqual(fmt_time(65), "1:05")
        self.assertEqual(fmt_time(3665), "1:01:05")


if __name__ == "__main__":
    unittest.main()
