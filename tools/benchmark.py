"""
Benchmark script: measures actual clicks per second (CPS), average interval,
maximum deviation, and CPU usage across different target intervals.

Run: py tools/benchmark.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker.config import DEFAULTS
from autoclicker.engine import ClickEngine


class DummyController:
    """No-op mouse controller for safe, high-speed timing benchmarks without moving the real cursor."""

    def __init__(self):
        self.position = (500, 500)

    def click(self, button, count=1):
        pass

    def press(self, button):
        pass

    def release(self, button):
        pass


def run_benchmark(intervals_ms=(1, 2, 5, 10, 20, 50, 100, 660), duration_s=1.5):
    print("Auto Clicker Timing & CPU Benchmark")
    print("=" * 84)
    print(
        f"{'Target (ms)':>11} | {'Target CPS':>10} | {'Actual CPS':>10} | "
        f"{'Avg (ms)':>10} | {'Max Dev (ms)':>12} | {'CPU %':>8}"
    )
    print("-" * 84)

    for ms in intervals_ms:
        eng = ClickEngine(controller_factory=DummyController)
        cfg = {
            **DEFAULTS,
            "action_mode": "Click",
            "interval": ms,
            "sound_on": False,
            "failsafe": False,
        }
        eng.start(cfg, warmup_s=0)
        time.sleep(duration_s)
        eng.stop()
        while eng.active:
            time.sleep(0.01)

        elapsed = eng.elapsed
        target_cps = 1000.0 / ms
        actual_cps = eng.count / elapsed if elapsed > 0 else 0.0
        sign = "+" if eng.max_deviation_ms >= 0 else ""
        print(
            f"{ms:11d} | {target_cps:10.1f} | {actual_cps:10.1f} | "
            f"{eng.avg_interval_ms:10.2f} | {sign}{eng.max_deviation_ms:11.2f} | "
            f"{eng.cpu_percent:7.1f}%"
        )


if __name__ == "__main__":
    run_benchmark()
