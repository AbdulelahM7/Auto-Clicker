"""Unit tests for interval/CPS conversions, 2-mode presets, hotkey preservation, and engine telemetry."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker import __version__
from autoclicker.config import (
    DEFAULTS,
    PRESET_MODES,
    WEAPONS,
    cps_to_interval_ms,
    effective,
    fmt_time,
    interval_ms_to_cps,
    key_label,
    load_presets,
    load_settings,
    mc_interval,
    merge_preset_preserving_globals,
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

    def test_two_preset_modes_only(self):
        self.assertEqual(PRESET_MODES, ("Default", "Sword (Minecraft)"))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "presets.json"
            presets = load_presets(path=p)
            self.assertEqual(list(presets.keys()), ["Default", "Sword (Minecraft)"])
            self.assertTrue(presets["Sword (Minecraft)"]["mc_mode"])
            self.assertEqual(presets["Sword (Minecraft)"]["mc_weapon"], "Sword")

    def test_default_preset_saves_and_persists_user_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "presets.json"
            presets = load_presets(path=p)
            presets["Default"] = {
                **DEFAULTS,
                "button": "Right",
                "custom_cps": 20.0,
                "interval": 50,
                "double": True,
            }
            save_presets(presets, path=p)
            reloaded = load_presets(path=p)
            self.assertEqual(reloaded["Default"]["button"], "Right")
            self.assertEqual(reloaded["Default"]["custom_cps"], 20.0)
            self.assertEqual(reloaded["Default"]["interval"], 50)
            self.assertTrue(reloaded["Default"]["double"])
            # Sword preset always stays fixed
            self.assertTrue(reloaded["Sword (Minecraft)"]["mc_mode"])
            self.assertEqual(reloaded["Sword (Minecraft)"]["interval"], 660)

    def test_preset_switch_never_overwrites_start_stop_hotkey(self):
        user_current = {
            **DEFAULTS,
            "hotkey": "f9",
            "topmost": True,
            "sound_on": False,
            "start_delay": 5,
        }
        sword_preset = load_presets()["Sword (Minecraft)"]
        merged = merge_preset_preserving_globals(user_current, sword_preset)
        self.assertEqual(merged["hotkey"], "f9")
        self.assertTrue(merged["topmost"])
        self.assertFalse(merged["sound_on"])
        self.assertEqual(merged["start_delay"], 5)
        self.assertTrue(merged["mc_mode"])

    def test_cps_and_interval_conversion_in_default_mode(self):
        self.assertEqual(cps_to_interval_ms(10.0), 100)
        self.assertEqual(cps_to_interval_ms(20.0), 50)
        self.assertEqual(cps_to_interval_ms(1.0), 1000)
        self.assertEqual(interval_ms_to_cps(100), 10.0)
        self.assertEqual(interval_ms_to_cps(50), 20.0)
        with self.assertRaises(ValueError):
            cps_to_interval_ms(0)
        with self.assertRaises(ValueError):
            interval_ms_to_cps(0)

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

    def test_sanitize_and_hotkey_collision_guard(self):
        corrupted = {
            "action_mode": "InvalidMode",
            "button": "InvalidBtn",
            "interval": -50,
            "custom_cps": 5000.0,
            "clicks": -10,
            "time_limit_min": 999999,
            "hotkey": "f8",
            "record_key": "f8",
            "mc_custom_speed": -5,
            "sequence_points": [[100, 200], "bad_point", [10]],
        }
        clean = sanitize_settings(corrupted)
        self.assertEqual(clean["action_mode"], "Click")
        self.assertEqual(clean["button"], "Left")
        self.assertEqual(clean["interval"], 1)
        self.assertEqual(clean["custom_cps"], 1000.0)
        self.assertEqual(clean["hotkey"], "f8")
        self.assertEqual(clean["record_key"], "f7")  # automatically shifted so F8 doesn't collide

    def test_save_and_load_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            custom = {**DEFAULTS, "interval": 250, "custom_cps": 4.0, "action_mode": "Hold", "button": "Right"}
            save_settings(custom, path=p)
            loaded = load_settings(path=p)
            self.assertEqual(loaded["interval"], 250)
            self.assertEqual(loaded["custom_cps"], 4.0)
            self.assertEqual(loaded["action_mode"], "Hold")
            self.assertEqual(loaded["button"], "Right")

    def test_engine_click_and_hold_modes(self):
        dummy = DummyMouse()
        eng = ClickEngine(controller_factory=lambda: dummy)
        cfg = {**DEFAULTS, "interval": 20, "clicks": 4, "sound_on": False, "failsafe": False}
        eng.start(cfg, warmup_s=0)
        deadline = time.time() + 2.0
        while eng.active and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(eng.count, 4)
        self.assertEqual(eng.reason, "done")
        self.assertIn("ms avg", eng.format_telemetry())

        # Hold mode test
        eng.start({**DEFAULTS, "action_mode": "Hold", "sound_on": False, "failsafe": False}, warmup_s=0)
        time.sleep(0.06)
        eng.stop()
        while eng.active:
            time.sleep(0.01)
        self.assertFalse(dummy.holding)
        self.assertEqual(eng.reason, "stopped")

    def test_helpers(self):
        self.assertEqual(key_label("f6"), "F6")
        self.assertEqual(key_label("vk65"), "Key 65")
        self.assertEqual(fmt_time(65), "1:05")
        self.assertEqual(fmt_time(3665), "1:01:05")


if __name__ == "__main__":
    unittest.main()
