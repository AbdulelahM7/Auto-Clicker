"""
Auto Clicker — customtkinter + pynput  (with Minecraft Java hit mode)
Run:      py auto_clicker.py
Requires: py -m pip install -r requirements.txt
"""

import ctypes
import sys

MUTEX_NAME = "Local\\AutoClicker_SingleInstance_Mutex_v1"
ERROR_ALREADY_EXISTS = 183
_MUTEX_HANDLE = None


def acquire_single_instance_mutex():
    """Ensure only one instance of Auto Clicker runs at a time on Windows so hotkeys don't double-fire."""
    global _MUTEX_HANDLE
    if not sys.platform.startswith("win"):
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except (AttributeError, OSError):
        return True


def main():
    if not acquire_single_instance_mutex():
        if sys.platform.startswith("win"):
            ctypes.windll.user32.MessageBoxW(
                0,
                (
                    "Auto Clicker is already running.\n\n"
                    "Only one instance can run at a time so the start/stop shortcut does not trigger twice."
                ),
                "Auto Clicker",
                0x00000030,  # MB_ICONWARNING
            )
        sys.exit(0)

    from autoclicker.gui import App

    App().mainloop()


if __name__ == "__main__":
    main()
