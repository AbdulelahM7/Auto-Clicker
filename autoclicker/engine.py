"""Click engine with Hold mode, timing accuracy & CPU telemetry, audio cues, and macro positions."""

import ctypes
import random
import sys
import threading
import time
import traceback

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None

try:
    import winsound
except ImportError:
    winsound = None

from autoclicker.config import CORNER, log_error


def get_mouse_button(name):
    if mouse is None:
        return name
    mapping = {
        "Left": mouse.Button.left,
        "Middle": mouse.Button.middle,
        "Right": mouse.Button.right,
    }
    return mapping.get(name, mouse.Button.left)


def key_id(key):
    """Stable string id for a pynput key (None if unusable)."""
    if keyboard is not None and isinstance(key, keyboard.Key):
        return key.name
    ch = getattr(key, "char", None)
    if ch and ch.isprintable():
        return ch.lower()
    vk = getattr(key, "vk", None)
    return f"vk{vk}" if vk is not None else None


def set_timer_resolution(on):
    """Ask Windows for 1 ms timer ticks (default is ~15 ms) for accurate short intervals."""
    if sys.platform.startswith("win"):
        try:
            winmm = ctypes.windll.winmm
            (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
        except (AttributeError, OSError) as exc:
            log_error(f"Timer resolution warning: {exc}")


def play_beep(started, enabled=True):
    """Play a non-blocking beep on start (high tone) and stop (low tone) via winsound."""
    if not enabled or winsound is None:
        return
    freq = 880 if started else 440
    threading.Thread(target=winsound.Beep, args=(freq, 85), daemon=True).start()


class ClickEngine:
    """Clicks or holds mouse button on a background thread with timing and CPU telemetry."""

    def __init__(self, controller_factory=None):
        self._stop = threading.Event()
        self._thread = None
        self._controller_factory = controller_factory or (lambda: mouse.Controller())
        self.count = 0
        self.phase = "idle"        # idle | countdown | running
        self.reason = ""           # done | time_limit | stopped | failsafe | error
        self.error = ""
        self.warmup_end = 0.0
        self.started_at = 0.0
        self.ended_at = 0.0

        # Performance & timing telemetry
        self.target_interval_ms = 0.0
        self.avg_interval_ms = 0.0
        self.max_deviation_ms = 0.0
        self.cpu_percent = 0.0
        self._cpu_started_at = 0.0
        self._cpu_ended_at = 0.0

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed(self):
        if not self.started_at:
            return 0.0
        end = time.perf_counter() if self.phase == "running" else self.ended_at
        return max(0.0, end - self.started_at)

    def format_telemetry(self):
        """Return post-run timing accuracy and CPU consumption summary."""
        parts = []
        if self.avg_interval_ms > 0 and self.count >= 2:
            sign = "+" if self.max_deviation_ms >= 0 else ""
            parts.append(
                f"{self.avg_interval_ms:.1f} ms avg (max dev {sign}{self.max_deviation_ms:.1f} ms)"
            )
        if self.elapsed > 0:
            parts.append(f"CPU {self.cpu_percent:.1f}%")
        return " · ".join(parts)

    def start(self, cfg, warmup_s):
        if self.active:
            return
        self._stop.clear()
        self.count = 0
        self.reason = self.error = ""
        self.started_at = self.ended_at = 0.0
        self.avg_interval_ms = 0.0
        self.max_deviation_ms = 0.0
        self.cpu_percent = 0.0
        self.target_interval_ms = float(cfg.get("interval", 100))
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

    @staticmethod
    def _apply_location(ctrl, loc_mode, fixed_pos, seq_pts, step_idx):
        if loc_mode == "Fixed":
            ctrl.position = fixed_pos
        elif loc_mode == "Sequence" and seq_pts:
            pt = seq_pts[step_idx % len(seq_pts)]
            ctrl.position = (pt[0], pt[1])

    def _update_cpu_usage(self, now_wall):
        wall_dt = now_wall - self.started_at
        if wall_dt > 0.001:
            cpu_dt = time.process_time() - self._cpu_started_at
            self.cpu_percent = max(0.0, (cpu_dt / wall_dt) * 100.0)

    def _run(self, cfg, warmup_s):
        set_timer_resolution(True)
        ctrl = None
        button = get_mouse_button(cfg.get("button", "Left"))
        action_mode = cfg.get("action_mode", "Click")
        sound_on = cfg.get("sound_on", True)
        holding = False
        try:
            ctrl = self._controller_factory()
            if warmup_s and self._stop.wait(warmup_s):
                self.reason = "stopped"
                return

            interval = cfg["interval"] / 1000.0
            target_ms = float(cfg["interval"])
            jitter = cfg["jitter"] / 1000.0 if cfg.get("jitter_on") else 0.0
            presses = 2 if cfg.get("double") else 1
            limit = cfg.get("clicks", 0)
            time_limit_s = cfg.get("time_limit_min", 0) * 60.0
            failsafe = cfg.get("failsafe", True)
            loc_mode = cfg.get("location_mode", "Cursor")
            fixed_pos = (int(cfg.get("fixed_x", 0)), int(cfg.get("fixed_y", 0)))
            seq_pts = cfg.get("sequence_points") or []

            self.phase = "running"
            self.started_at = next_t = time.perf_counter()
            self._cpu_started_at = time.process_time()
            play_beep(started=True, enabled=sound_on)

            if action_mode == "Hold":
                self._apply_location(ctrl, loc_mode, fixed_pos, seq_pts, 0)
                ctrl.press(button)
                holding = True
                self.count = 1
                while not self._stop.is_set():
                    if failsafe and self._in_corner(ctrl):
                        self.reason = "failsafe"
                        return
                    now = time.perf_counter()
                    self._update_cpu_usage(now)
                    if time_limit_s > 0 and (now - self.started_at) >= time_limit_s:
                        self.reason = "time_limit"
                        return
                    if self._stop.wait(0.05):
                        self.reason = "stopped"
                        return
                self.reason = "stopped"
                return

            # Repeated Click mode with interval & deviation tracking
            last_click_t = None
            interval_sum_ms = 0.0
            interval_samples = 0
            max_abs_dev_ms = 0.0
            signed_max_dev_ms = 0.0

            while True:
                if failsafe and self._in_corner(ctrl):
                    self.reason = "failsafe"
                    return
                now_pre = time.perf_counter()
                if time_limit_s > 0 and (now_pre - self.started_at) >= time_limit_s:
                    self.reason = "time_limit"
                    return

                self._apply_location(ctrl, loc_mode, fixed_pos, seq_pts, self.count)
                ctrl.click(button, presses)
                click_t = time.perf_counter()
                self.count += 1

                if last_click_t is not None:
                    actual_ms = (click_t - last_click_t) * 1000.0
                    interval_samples += 1
                    interval_sum_ms += actual_ms
                    self.avg_interval_ms = interval_sum_ms / interval_samples
                    dev_ms = actual_ms - target_ms
                    if abs(dev_ms) >= max_abs_dev_ms:
                        max_abs_dev_ms = abs(dev_ms)
                        signed_max_dev_ms = dev_ms
                        self.max_deviation_ms = signed_max_dev_ms

                last_click_t = click_t
                self._update_cpu_usage(click_t)

                if limit and self.count >= limit:
                    self.reason = "done"
                    return
                if time_limit_s > 0 and (click_t - self.started_at) >= time_limit_s:
                    self.reason = "time_limit"
                    return

                next_t += interval + (random.uniform(0, jitter) if jitter else 0.0)
                now = time.perf_counter()
                next_t = max(next_t, now)   # fell behind: resync instead of bursting
                if self._sleep_until(next_t):
                    self.reason = "stopped"
                    return
        except (OSError, RuntimeError, ValueError, TypeError) as exc:  # e.g. missing OS permission
            self.error = str(exc) or exc.__class__.__name__
            self.reason = "error"
            log_error(traceback.format_exc())
        finally:
            if holding and ctrl is not None:
                try:
                    ctrl.release(button)
                except (OSError, RuntimeError) as exc:
                    log_error(f"Mouse release warning: {exc}")
            self.ended_at = time.perf_counter()
            self._update_cpu_usage(self.ended_at)
            self.phase = "idle"
            set_timer_resolution(False)
            if self.started_at > 0:
                play_beep(started=False, enabled=sound_on)
