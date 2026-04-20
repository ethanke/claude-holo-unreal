"""Unreal Engine editor focus helpers.

`focus_ue()` brings the UE editor window to the foreground reliably — handles
Windows' SetForegroundWindow quirk (requires recent input focus) via the alt-key
trick, restores minimized windows, and optionally parks the mouse in the
viewport to clear any stale hover tooltips.

Requires `pywin32` and `psutil`. Without them the helpers degrade to best-effort
screenshot-only via the `vision` module's `capture()`.
"""
from __future__ import annotations

import subprocess
import time
from typing import Any

from PIL import Image

try:
    import win32con  # type: ignore[import-not-found]
    import win32gui  # type: ignore[import-not-found]
    import win32process  # type: ignore[import-not-found]
    _HAVE_WIN32 = True
except Exception:
    win32con = win32gui = win32process = None  # type: ignore[assignment]
    _HAVE_WIN32 = False

try:
    import psutil  # type: ignore[import-not-found]
    _HAVE_PSUTIL = True
except Exception:
    psutil = None  # type: ignore[assignment]
    _HAVE_PSUTIL = False


def _pid_is_ue(pid: int, exe: str = "UnrealEditor.exe") -> bool:
    if _HAVE_PSUTIL and psutil is not None:
        try:
            return psutil.Process(pid).name().lower() == exe.lower()
        except Exception:
            return False
    try:
        r = subprocess.run(
            ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=3,
        )
        return exe in (r.stdout or "")
    except Exception:
        return False


def find_ue_hwnd(exe: str = "UnrealEditor.exe") -> int | None:
    """Return the HWND of the most likely UE main editor window, or None."""
    if not _HAVE_WIN32:
        return None
    hits: list[tuple[int, int]] = []

    def cb(hwnd: int, _: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return
        if _pid_is_ue(pid, exe):
            score = 10 if "Unreal" in title else 0
            score += 5 if "- Unreal" in title else 0
            hits.append((score, hwnd))

    win32gui.EnumWindows(cb, None)
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def focus_ue(timeout_s: float = 3.0, *, park_mouse: bool = True) -> bool:
    """Bring the Unreal Engine editor window to the foreground.

    Returns True on success. Uses the alt-key trick to satisfy Windows'
    SetForegroundWindow policy, restores minimized windows, and (optionally)
    parks the mouse in the viewport center to clear leftover hover tooltips.
    """
    if not _HAVE_WIN32:
        return False
    hwnd = find_ue_hwnd()
    if hwnd is None:
        return False
    try:
        import ctypes
        # Alt-down + alt-up — grants recent-input-focus so SetForegroundWindow wins.
        try:
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
        except Exception:
            pass
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        return False

    deadline = time.time() + timeout_s
    ok = False
    while time.time() < deadline:
        try:
            if win32gui.GetForegroundWindow() == hwnd:
                ok = True
                break
        except Exception:
            break
        time.sleep(0.05)

    if park_mouse:
        try:
            rect = win32gui.GetWindowRect(hwnd)
            cx = (rect[0] + rect[2]) // 2
            cy = (rect[1] + rect[3]) // 2
            import ctypes
            ctypes.windll.user32.SetCursorPos(cx, cy)
        except Exception:
            pass
    return ok


def capture_window(hwnd: int | None = None) -> tuple[Image.Image, tuple[int, int]]:
    """Screenshot a window (default: the UE editor). Returns (image, (left, top))."""
    from .vision import capture, find_window

    from ._env import default_window_title

    if hwnd is None:
        hwnd, _ = find_window(default_window_title())
    return capture(hwnd)


__all__ = ["find_ue_hwnd", "focus_ue", "capture_window"]
