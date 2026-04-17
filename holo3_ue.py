"""Holo3 → Unreal Engine viewport click agent.

Screenshots the Unreal Editor window, asks Holo3-35B-A3B (H Company's vision
model) where the described element is, then synthesizes a click at the returned
pixel. Pure Win32 ctypes — no pywin32 or pyautogui dependency.

CLI usage:
    python holo3_ue.py "the Blueprint menu in the toolbar"
    python holo3_ue.py "the play button" --dry-run
    python holo3_ue.py "Save" --window-title "MyProject" --save debug.png
    python holo3_ue.py --list-windows
    python holo3_ue.py --press "ctrl+s"                     # keyboard chord
    python holo3_ue.py "the search box" --type "HelloWorld" # click + type

Library usage:
    from holo3_ue import click_by_description, localize_in_window, type_into
    click_by_description("the Play button")
    x, y, screen_x, screen_y = localize_in_window("Save")
    type_into("the search box", "HelloWorld")
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import io
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageGrab

DEFAULT_BASE_URL = "https://api.hcompany.ai/v1/"
DEFAULT_MODEL = "holo3-35b-a3b"
DEFAULT_WINDOW_TITLE = "Unreal Editor"

LOCALIZE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["x", "y"],
    "properties": {
        "x": {"type": "integer", "description": "pixel from left edge of the screenshot"},
        "y": {"type": "integer", "description": "pixel from top edge of the screenshot"},
    },
}


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

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user32.mouse_event.restype = None

# SendInput plumbing (keyboard) ----------------------------------------------
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
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


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

# Virtual-key code table. Extended keys need KEYEVENTF_EXTENDEDKEY.
_EXTENDED_VK = {0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B, 0x5C}
_MOD_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_NAMED_VK = {
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
_NAMED_VK["f13"] = 0x7C  # safe no-binding key used by CLI smoke test


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
    # Surrogate pair handling for chars outside the BMP
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


def list_windows() -> list[tuple[int, str]]:
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
    raise SystemExit(f"no visible window matched '{title_substr}'. Try --list-windows.")


def get_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        raise OSError(f"GetWindowRect failed: {ctypes.get_last_error()}")
    return r.left, r.top, r.right, r.bottom


def capture(hwnd: int) -> tuple[Image.Image, tuple[int, int]]:
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    left, top, right, bottom = get_rect(hwnd)
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    return img, (left, top)


def localize(client: OpenAI, model: str, image: Image.Image, description: str, temperature: float = 0.0) -> tuple[int, int]:
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
        raise RuntimeError(f"coords {x},{y} out of bounds for {image.width}x{image.height}")
    return x, y


def click_at(screen_x: int, screen_y: int) -> None:
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)


def right_click_at(screen_x: int, screen_y: int) -> None:
    """Right-click at absolute screen pixel."""
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, None)
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, None)


def double_click_at(screen_x: int, screen_y: int, interval: float = 0.08) -> None:
    """Two left clicks separated by `interval` seconds."""
    click_at(screen_x, screen_y)
    time.sleep(interval)
    click_at(screen_x, screen_y)


def send_text(text: str, per_char_delay: float = 0.01) -> None:
    """Type Unicode text into the focused window via SendInput."""
    for ch in text:
        _send_unicode_char(ch)
        if per_char_delay > 0:
            time.sleep(per_char_delay)


def press_key(key: str, modifiers: list[str] | None = None) -> None:
    """Press `key` with optional modifier chord (e.g. ["ctrl","shift"])."""
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


def _make_client(base_url: str | None = None, api_key: str | None = None) -> OpenAI:
    load_env()
    url = base_url or os.environ.get("HAI_MODEL_URL", DEFAULT_BASE_URL)
    key = api_key or os.environ.get("HAI_API_KEY")
    if not key:
        raise RuntimeError("HAI_API_KEY not set (env, .env, or api_key arg)")
    return OpenAI(base_url=url, api_key=key)


def localize_in_window(
    description: str,
    *,
    window_title: str = DEFAULT_WINDOW_TITLE,
    model: str | None = None,
    client: OpenAI | None = None,
    temperature: float = 0.0,
) -> tuple[int, int, int, int]:
    """Screenshot UE window, ask Holo3 where the element is.

    Returns (window_x, window_y, screen_x, screen_y). Does not click.
    """
    hwnd, _ = find_window(window_title)
    image, (win_left, win_top) = capture(hwnd)
    c = client or _make_client()
    m = model or os.environ.get("HAI_MODEL_NAME", DEFAULT_MODEL)
    x, y = localize(c, m, image, description, temperature)
    return x, y, win_left + x, win_top + y


def click_by_description(
    description: str,
    *,
    window_title: str = DEFAULT_WINDOW_TITLE,
    model: str | None = None,
    client: OpenAI | None = None,
    temperature: float = 0.0,
    dry_run: bool = False,
    settle_seconds: float = 0.0,
) -> tuple[int, int]:
    """Compose capture + localize + click. Returns (screen_x, screen_y).

    Set dry_run=True to skip the click. settle_seconds pauses before clicking
    (useful if you want to Ctrl+C between localize and click during tuning).
    """
    _, _, sx, sy = localize_in_window(
        description, window_title=window_title, model=model, client=client, temperature=temperature
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
    window_title: str = DEFAULT_WINDOW_TITLE,
    settle_seconds: float = 0.0,
    **kw,
) -> tuple[int, int]:
    """Like click_by_description but synthesizes a right-click."""
    dry_run = kw.pop("dry_run", False)
    _, _, sx, sy = localize_in_window(description, window_title=window_title, **kw)
    if dry_run:
        return sx, sy
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    right_click_at(sx, sy)
    return sx, sy


def type_into(
    description: str,
    text: str,
    *,
    window_title: str = DEFAULT_WINDOW_TITLE,
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
    "list_windows",
    "find_window",
    "capture",
    "localize",
    "click_at",
    "right_click_at",
    "double_click_at",
    "send_text",
    "press_key",
    "localize_in_window",
    "click_by_description",
    "right_click_by_description",
    "type_into",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_WINDOW_TITLE",
]


def load_env() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    p = argparse.ArgumentParser(description="Holo3-powered viewport clicker for Unreal Engine.")
    p.add_argument("description", nargs="?", help="what to find, e.g. 'the Play button'")
    p.add_argument("--window-title", default=DEFAULT_WINDOW_TITLE, help="substring of UE window title")
    p.add_argument("--model", default=os.environ.get("HAI_MODEL_NAME", DEFAULT_MODEL))
    p.add_argument("--base-url", default=os.environ.get("HAI_MODEL_URL", DEFAULT_BASE_URL))
    p.add_argument("--api-key", default=os.environ.get("HAI_API_KEY"))
    p.add_argument("--dry-run", action="store_true", help="localize but do not click/type/press")
    p.add_argument("--save", metavar="PATH", help="save the annotated screenshot here")
    p.add_argument("--list-windows", action="store_true")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--right-click", action="store_true", help="right-click instead of left-click")
    p.add_argument("--double-click", action="store_true", help="double-click instead of single")
    p.add_argument("--type", dest="type_text", metavar="TEXT", help="after clicking, type this text")
    p.add_argument("--press", metavar="KEY[+mods]", help="press a key chord, e.g. 'ctrl+s' or 'f5'")
    args = p.parse_args()

    if args.list_windows:
        for hwnd, title in list_windows():
            print(f"0x{hwnd:08x}  {title}")
        return 0

    # --press without a description: just send the key chord, no window focus.
    if args.press and not args.description:
        parts = [p_.strip() for p_ in args.press.split("+") if p_.strip()]
        if not parts:
            p.error("--press value is empty")
        key = parts[-1]
        mods = parts[:-1]
        if args.dry_run:
            print(f"dry-run: would press {'+'.join(mods + [key]) if mods else key}")
            return 0
        press_key(key, modifiers=mods or None)
        print(f"pressed {'+'.join(mods + [key]) if mods else key}")
        return 0

    if not args.description:
        p.error("description is required unless --list-windows or --press")
    if not args.api_key:
        p.error("HAI_API_KEY not set (env, .env, or --api-key)")

    hwnd, title = find_window(args.window_title)
    print(f"window: {title}")

    image, (win_left, win_top) = capture(hwnd)
    print(f"captured {image.width}x{image.height} at screen ({win_left},{win_top})")

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    x, y = localize(client, args.model, image, args.description, args.temperature)
    screen_x, screen_y = win_left + x, win_top + y
    print(f"localized: window ({x},{y}) -> screen ({screen_x},{screen_y})")

    if args.save:
        from PIL import ImageDraw
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        draw.line([(x - 15, y), (x + 15, y)], fill="red", width=3)
        draw.line([(x, y - 15), (x, y + 15)], fill="red", width=3)
        draw.ellipse([x - 10, y - 10, x + 10, y + 10], outline="red", width=2)
        annotated.save(args.save)
        print(f"saved annotated screenshot to {args.save}")

    if args.dry_run:
        print("dry-run: skipping click and any follow-up text/key action")
        return 0

    print("clicking in 1s (Ctrl+C to cancel)...")
    time.sleep(1.0)
    if args.right_click:
        right_click_at(screen_x, screen_y)
        print("right-clicked.")
    elif args.double_click:
        double_click_at(screen_x, screen_y)
        print("double-clicked.")
    else:
        click_at(screen_x, screen_y)
        print("clicked.")

    if args.type_text:
        time.sleep(0.1)
        send_text(args.type_text)
        print(f"typed {len(args.type_text)} chars.")

    if args.press:
        parts = [p_.strip() for p_ in args.press.split("+") if p_.strip()]
        if parts:
            key = parts[-1]
            mods = parts[:-1]
            time.sleep(0.05)
            press_key(key, modifiers=mods or None)
            print(f"pressed {'+'.join(mods + [key]) if mods else key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
