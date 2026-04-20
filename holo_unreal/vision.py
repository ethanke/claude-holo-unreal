"""Holo3 vision grounding + Win32 input primitives for Unreal Editor.

Screenshots the target UE window, asks Holo3-35B-A3B (H Company) where the
described element is, then synthesizes a click at the returned pixel.

Pure `ctypes` underneath — no `pywin32`, no `pyautogui`, no Selenium. Runtime
dependencies: `openai` (managed API client) and `Pillow` (screenshot grab).

All `*_by_description` helpers target the window whose title case-insensitively
matches `window_title` (default "Unreal Editor" — overridable per-call or via
the `HOLO_UNREAL_WINDOW_TITLE` env var).

Library usage:
    from holo_unreal import (
        click_by_description, localize_in_window, type_into, press_key,
    )
    click_by_description("the Play button")
    x, y, sx, sy = localize_in_window("Save All")   # dry-run coords
    type_into("the search box", "MyActor")
    press_key("s", modifiers=["ctrl"])
"""
from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import sys
import time
from ctypes import wintypes
from typing import TYPE_CHECKING

from PIL import Image, ImageGrab

from ._env import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_WINDOW_TITLE,
    default_window_title,
    hai_api_key,
    hai_base_url,
    hai_model,
    load_env,
)

if TYPE_CHECKING:  # pragma: no cover
    from openai import OpenAI

LOCALIZE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["x", "y"],
    "properties": {
        "x": {"type": "integer", "description": "pixel from left edge of the screenshot"},
        "y": {"type": "integer", "description": "pixel from top edge of the screenshot"},
    },
}


# ---------------------------------------------------------------------- Win32

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    ]
    user32.mouse_event.restype = None

    # Make the process DPI-aware so coordinates match physical pixels.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
else:
    user32 = None  # type: ignore[assignment]
    WNDENUMPROC = None  # type: ignore[assignment]

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001

ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


if sys.platform == "win32":
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT


# Virtual-key code table. Extended keys need KEYEVENTF_EXTENDEDKEY.
_EXTENDED_VK = {
    0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B, 0x5C,
}
_MOD_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_NAMED_VK: dict[str, int] = {
    "enter": 0x0D, "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B, "esc": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
for _i in range(1, 13):
    _NAMED_VK[f"f{_i}"] = 0x6F + _i  # F1 = 0x70 ... F12 = 0x7B
_NAMED_VK["f13"] = 0x7C


def _vk_for(key: str) -> int:
    k = key.lower().strip()
    if k in _NAMED_VK:
        return _NAMED_VK[k]
    if len(k) == 1:
        c = k.upper()
        if "A" <= c <= "Z" or "0" <= c <= "9":
            return ord(c)
    raise ValueError(f"unknown key: {key!r}")


def _send_vk(vk: int, key_up: bool = False) -> None:
    flags = KEYEVENTF_KEYUP if key_up else 0
    if vk in _EXTENDED_VK:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _send_unicode_char(ch: str) -> None:
    code = ord(ch)
    # Surrogate pair handling for chars outside the BMP.
    if code > 0xFFFF:
        high = 0xD800 + ((code - 0x10000) >> 10)
        low = 0xDC00 + ((code - 0x10000) & 0x3FF)
        for cp in (high, low):
            for up in (False, True):
                inp = _INPUT(type=INPUT_KEYBOARD)
                inp.u.ki = _KEYBDINPUT(
                    wVk=0, wScan=cp,
                    dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0),
                    time=0, dwExtraInfo=0,
                )
                user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        return
    for up in (False, True):
        inp = _INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = _KEYBDINPUT(
            wVk=0, wScan=code,
            dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0),
            time=0, dwExtraInfo=0,
        )
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


# --------------------------------------------------------- window discovery

def list_windows() -> list[tuple[int, str]]:
    """Enumerate visible top-level windows. Returns [(hwnd, title), ...]."""
    if sys.platform != "win32":
        raise RuntimeError("list_windows() is Windows-only")

    results: list[tuple[int, str]] = []

    @WNDENUMPROC
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        results.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return results


def find_window(title_substr: str) -> tuple[int, str]:
    needle = title_substr.lower()
    for hwnd, title in list_windows():
        if needle in title.lower():
            return hwnd, title
    raise RuntimeError(
        f"no visible window matched {title_substr!r}. "
        f"Try `hue list-windows` to see options."
    )


def get_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        raise OSError(f"GetWindowRect failed: {ctypes.get_last_error()}")
    return r.left, r.top, r.right, r.bottom


def capture(hwnd: int) -> tuple[Image.Image, tuple[int, int]]:
    """Foreground + screenshot the window. Returns (image, (left, top))."""
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    left, top, right, bottom = get_rect(hwnd)
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    return img, (left, top)


# ----------------------------------------------------------- OpenAI client

def _make_client(base_url: str | None = None, api_key: str | None = None) -> "OpenAI":
    from openai import OpenAI

    load_env()
    url = base_url or hai_base_url()
    key = api_key or hai_api_key()
    if not key:
        raise RuntimeError(
            "HAI_API_KEY not set. Put it in .env, export it, or pass api_key=...."
        )
    return OpenAI(base_url=url, api_key=key)


# ------------------------------------------------------------ localization

def localize(
    client: "OpenAI",
    model: str,
    image: Image.Image,
    description: str,
    temperature: float = 0.0,
) -> tuple[int, int]:
    """Ask Holo3 where `description` is in `image`. Returns (x, y) in image px."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()
    prompt = (
        "You are a UI localizer for an Unreal Engine editor screenshot. "
        f"Find: {description}. "
        "Return the exact pixel coordinates (x, y) to click inside the screenshot. "
        f"The screenshot is {image.width}x{image.height} pixels; origin (0,0) is the top-left."
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        extra_body={
            "structured_outputs": {"json": LOCALIZE_SCHEMA},
            "chat_template_kwargs": {"enable_thinking": False},
        },
        temperature=temperature,
        max_tokens=1024,
    )
    content = resp.choices[0].message.content
    if not content:
        raise RuntimeError(f"Holo3 returned empty content. Full response: {resp}")
    parsed = json.loads(content)
    x, y = int(parsed["x"]), int(parsed["y"])
    if not (0 <= x < image.width and 0 <= y < image.height):
        raise RuntimeError(
            f"Holo3 coords {x},{y} out of bounds for {image.width}x{image.height}"
        )
    return x, y


# ------------------------------------------------------------------ input

def click_at(screen_x: int, screen_y: int) -> None:
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)


def right_click_at(screen_x: int, screen_y: int) -> None:
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, None)
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, None)


def double_click_at(screen_x: int, screen_y: int, interval: float = 0.08) -> None:
    click_at(screen_x, screen_y)
    time.sleep(interval)
    click_at(screen_x, screen_y)


def send_text(text: str, per_char_delay: float = 0.01) -> None:
    for ch in text:
        _send_unicode_char(ch)
        if per_char_delay > 0:
            time.sleep(per_char_delay)


def press_key(key: str, modifiers: list[str] | None = None) -> None:
    mods = [m.lower().strip() for m in (modifiers or [])]
    for m in mods:
        if m not in _MOD_VK:
            raise ValueError(f"unknown modifier: {m!r}")
    vk = _vk_for(key)
    mod_vks = [_MOD_VK[m] for m in mods]
    for mvk in mod_vks:
        _send_vk(mvk, key_up=False)
    _send_vk(vk, key_up=False)
    time.sleep(0.02)
    _send_vk(vk, key_up=True)
    for mvk in reversed(mod_vks):
        _send_vk(mvk, key_up=True)


def press_chord(combo: str) -> None:
    """Helper: parse `ctrl+shift+s` into press_key."""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty key combo")
    press_key(parts[-1], modifiers=parts[:-1] or None)


# ------------------------------------------------------------ composition

def localize_in_window(
    description: str,
    *,
    window_title: str | None = None,
    model: str | None = None,
    client: "OpenAI | None" = None,
    temperature: float = 0.0,
) -> tuple[int, int, int, int]:
    """Screenshot the UE window, ask Holo3 where the element is.

    Returns (window_x, window_y, screen_x, screen_y). Does not click.
    """
    title = window_title or default_window_title()
    hwnd, _ = find_window(title)
    image, (win_left, win_top) = capture(hwnd)
    c = client or _make_client()
    m = model or hai_model()
    x, y = localize(c, m, image, description, temperature)
    return x, y, win_left + x, win_top + y


def click_by_description(
    description: str,
    *,
    window_title: str | None = None,
    model: str | None = None,
    client: "OpenAI | None" = None,
    temperature: float = 0.0,
    dry_run: bool = False,
    settle_seconds: float = 0.0,
) -> tuple[int, int]:
    """Capture → localize → click. Returns (screen_x, screen_y)."""
    _, _, sx, sy = localize_in_window(
        description,
        window_title=window_title,
        model=model,
        client=client,
        temperature=temperature,
    )
    if dry_run:
        return sx, sy
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    click_at(sx, sy)
    return sx, sy


def right_click_by_description(
    description: str,
    *,
    window_title: str | None = None,
    settle_seconds: float = 0.0,
    **kw,
) -> tuple[int, int]:
    dry_run = kw.pop("dry_run", False)
    _, _, sx, sy = localize_in_window(description, window_title=window_title, **kw)
    if dry_run:
        return sx, sy
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    right_click_at(sx, sy)
    return sx, sy


def double_click_by_description(
    description: str,
    *,
    window_title: str | None = None,
    settle_seconds: float = 0.0,
    **kw,
) -> tuple[int, int]:
    dry_run = kw.pop("dry_run", False)
    _, _, sx, sy = localize_in_window(description, window_title=window_title, **kw)
    if dry_run:
        return sx, sy
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    double_click_at(sx, sy)
    return sx, sy


def type_into(
    description: str,
    text: str,
    *,
    window_title: str | None = None,
    settle_seconds: float = 0.1,
    **kw,
) -> tuple[int, int]:
    """Click the described field to focus it, then type `text`."""
    dry_run = kw.pop("dry_run", False)
    _, _, sx, sy = localize_in_window(description, window_title=window_title, **kw)
    if dry_run:
        return sx, sy
    click_at(sx, sy)
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    send_text(text)
    return sx, sy


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_WINDOW_TITLE",
    "LOCALIZE_SCHEMA",
    "capture",
    "click_at",
    "click_by_description",
    "double_click_at",
    "double_click_by_description",
    "find_window",
    "get_rect",
    "list_windows",
    "localize",
    "localize_in_window",
    "press_chord",
    "press_key",
    "right_click_at",
    "right_click_by_description",
    "send_text",
    "type_into",
]
