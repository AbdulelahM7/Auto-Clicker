# Changelog

All notable changes to this project are documented in this file.

## [1.0.1] - 2026-10-27

### Fixed
- **High-DPI Window Sizing & Scrolling:** Replaced fixed `500x700` layout with dynamic screen-aware height calculation and scrollable `CTkScrollableFrame` pages so the **Start** button is never clipped at 150% Windows scaling on 1080p displays.
- **Single-Instance Lock:** Added a Windows named Mutex (`Local\AutoClicker_SingleInstance_Mutex_v1`) so launching a second copy warns the user and exits instead of double-triggering `F6`.
- **Single Source of Version:** Unified `__version__ = "1.0.1"` in `autoclicker/__init__.py` and configured `build.bat`, `installer/AutoClicker.iss`, and `.github/workflows/release.yml` to read it automatically.
- **Documentation & Licensing:** Added `THIRD_PARTY_NOTICES.md`, Minecraft server/Mojang disclaimer, and SignPath Code Signing Policy in `README.md` and `README.ar.md`.

### Added
- **Performance & Timing Telemetry:** Displays average actual interval, maximum deviation from target (`ms`), and CPU usage (`time.process_time()`) after each session.
- **UI Refresh Throttling:** Reduced live statistics label updates from 20 Hz to 4 Hz (250 ms) to minimize UI overhead.
- **Benchmark Tool:** Added `tools/benchmark.py` to measure actual CPS vs target CPS and CPU load across intervals.
- **Hold Mode:** Added continuous mouse hold mode (`Hold`) for breaking blocks or AFK farming in Minecraft.
- **Audio Cues:** Added optional `winsound` start/stop beeps for background feedback when the window is behind a game.
- **Presets:** Added built-in and customizable presets (`Sword (Minecraft)`, `Mob Farm`, `Mining / Break Blocks (Hold)`, `AFK Right-Click`) with one-click switching.
- **Time Limit:** Added *"Stop after (min, 0=∞)"* timer option.
- **More Minecraft Weapons & Tools:** Added Pickaxe, Shovel, Hoe tiers, Spear, and a **Custom speed** option.
- **Location Macro:** Added `Cursor`, `Fixed`, and `Sequence` click location modes with `F8` coordinate recording.
- **System Tray & Update Checker:** Added optional minimize-to-tray via `pystray` and one-click GitHub Releases update checking.
- **Code Modularization, Tests & CI:** Split codebase into `autoclicker/` (`config.py`, `engine.py`, `gui.py`), added `tests/test_logic.py`, upgraded `.github/workflows/ci.yml` (`ruff`, `pytest`, and PyInstaller dry-run on PRs), and added Dependabot and community templates.

## [1.0.0] - 2026-10-25
- Initial public release with CustomTkinter dark UI and Minecraft Java hit mode.
