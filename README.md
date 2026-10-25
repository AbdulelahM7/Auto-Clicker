<div align="center">

<img src="assets/icon.png" width="112" alt="Auto Clicker icon">

# Auto Clicker

A lightweight, dark-mode auto clicker for Windows with a built-in **Minecraft Java hit mode** that times every swing to your weapon's attack cooldown.

![Platform](https://img.shields.io/badge/platform-Windows-4A63D8)
![Python](https://img.shields.io/badge/python-3.9%2B-4A63D8)
![License](https://img.shields.io/badge/license-MIT-4A63D8)

**English** · [العربية](README.ar.md)

</div>

<!-- Add a screenshot: save it as docs/screenshot.png and uncomment the next line.
![Screenshot](docs/screenshot.png)
-->

## Features

- **Mouse button**: left, middle or right
- **Interval** in milliseconds, with a **click limit** (`0` = unlimited)
- **Double click** option
- **Random extra delay** to vary the timing
- **Live counter** with elapsed time and clicks per second
- **Global start/stop key** (default `F6`) that works from any window, and you can **change it** in *Options*
- **Minecraft hit mode**: pick your weapon and the interval is set for you (see below)
- **Corner safety stop**: move the cursor to the top-left corner to halt clicking instantly
- **Always on top** option, and settings are **saved automatically**
- Drift-free timing with 1 ms timer resolution on Windows, so short intervals stay accurate
- Input validation with clear messages, and errors are logged instead of crashing the app

## Download

Get the latest build from the **[Releases](../../releases/latest)** page:

| File | What it is |
|---|---|
| `AutoClicker-Setup-x.y.z.exe` | Installer (Start menu entry, optional desktop shortcut, uninstaller). No admin rights needed. |
| `AutoClicker-portable-x.y.z.exe` | Single file, no installation. |
| `SHA256SUMS.txt` | Checksums to verify your download. |

> **Windows SmartScreen / antivirus:** the builds are not code-signed, so Windows may show *"Windows protected your PC"*. Click **More info → Run anyway**. Some antivirus tools also flag any program that registers a global keyboard hook (needed to detect the start/stop key). The full source is in this repository, so you can read it or [build it yourself](#build-from-source).

## Usage

1. Move the mouse over what you want to click.
2. Press **F6** to start, and press it again to stop. (The on-screen **Start** button begins after a short delay so you can move the cursor off the button first. You can change the delay in *Options*.)
3. To change the key, open **Options**, click the key box, then press the new key. `Esc` cancels.

Tip: function keys are the safest choice. A letter key would also trigger while you type in other apps.

## Minecraft hit mode

In **Minecraft: Java Edition**, a weapon deals reduced damage (and no critical or sweep hits) unless its attack cooldown has fully recharged. Clicking faster than that just wastes swings.

Turn on **Minecraft hit** and pick your weapon. The interval is calculated for a fully charged hit and every other click setting is locked (greyed out). Turn it off and your own settings come back exactly as you left them.

Full charge takes `20 ÷ attack speed` game ticks (1 tick = 50 ms). The interval is rounded up to a whole tick, plus a 10 ms safety margin:

| Weapon | Attack speed | Interval |
|---|---|---|
| Sword (all types) | 1.6 | 660 ms |
| Axe: wood / stone / copper | 0.8 | 1260 ms |
| Axe: iron | 0.9 | 1160 ms |
| Axe: gold / diamond / netherite | 1.0 | 1010 ms |
| Trident | 1.1 | 960 ms |
| Mace | 0.6 | 1710 ms |
| Fist | 4.0 | 260 ms |

Notes:
- **Java Edition only.** Bedrock Edition has no attack cooldown.
- Other items (pickaxes, shovels, hoes, spears) have different speeds and aren't listed yet. Use the normal mode with your own interval for those.
- The game processes input once per tick, so results can vary by one tick (50 ms).

## Build from source

Requires Windows and Python 3.9+ (the `py` launcher).

```powershell
git clone https://github.com/E7TRAF702/auto-clicker.git
cd auto-clicker
py -m pip install -r requirements.txt
py auto_clicker.py
```

### Build the exe and installer

```powershell
build.bat
```

This produces:

- `dist-portable\AutoClicker-portable.exe`: single-file exe
- `dist-installer\AutoClicker-Setup-<version>.exe`: installer, built with [Inno Setup 6](https://jrsoftware.org/isdl.php) (skipped if it isn't installed)

Set the version at the top of `build.bat` and in `installer/AutoClicker.iss` (or pass `/DAppVersion=...`).

### Publish a release (GitHub Actions)

Pushing a version tag builds everything on GitHub and attaches the files to a new Release:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

## Settings and logs

Saved in `%APPDATA%\AutoClicker\`:

- `settings.json`: your options (delete it to reset)
- `error.log`: details if something goes wrong

## Privacy

Everything runs locally. The app makes no network connections and collects no data. It listens to the keyboard only to detect your start/stop key, and nothing is recorded or stored.

## Troubleshooting

| Problem | Fix |
|---|---|
| Clicks don't register in some windows | Windows blocks input into apps running as administrator. Run Auto Clicker as administrator too. |
| Clicking stops immediately | The cursor is in the top-left corner (safety stop). Move it away or turn the option off. |
| The key doesn't react | Another app may be using the same key. Choose a different one in *Options*. |
| Very short intervals miss clicks | Some apps can't process input that fast. Try a longer interval. |

macOS and Linux: the code is built on cross-platform libraries and may run, but it is only developed and tested for Windows. On macOS you must grant Accessibility permission to the app.

## License

[MIT](LICENSE)
