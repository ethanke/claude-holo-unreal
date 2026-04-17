"""Benchmark harness for the Holo3-UE vision clicker.

Measures per-task timings (window find, capture, localize, click) against a
live Unreal Editor window; writes bench_out/report.md + annotated PNGs.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

# Committed API only. The parallel agent is adding press_key / send_text /
# right_click_by_description / type_into / double_click_at — import lazily.
from holo3_ue import (
    DEFAULT_MODEL, DEFAULT_WINDOW_TITLE,
    capture, click_at, click_by_description,
    find_window, localize, localize_in_window,
)

try:
    from holo3_ue import press_key  # type: ignore
    HAVE_EXT = True
except ImportError:
    HAVE_EXT = False

try:
    from holo3_ue import _make_client  # type: ignore
except ImportError:
    from openai import OpenAI

    def _make_client():  # type: ignore[no-redef]
        return OpenAI(
            base_url=os.environ.get("HAI_MODEL_URL", "https://api.hcompany.ai/v1/"),
            api_key=os.environ.get("HAI_API_KEY", ""),
        )


TASKS = [
    {"id": "locate-file-menu",      "kind": "localize_only", "description": "the File menu item in the top menu bar",               "expect_change": False},
    {"id": "click-file-menu",       "kind": "click",         "description": "the File menu item in the top menu bar",               "expect_change": True},
    {"id": "close-file-menu",       "kind": "key",           "description": "escape",                                               "expect_change": False},
    {"id": "locate-play-button",    "kind": "localize_only", "description": "the green Play button in the main toolbar",            "expect_change": False},
    {"id": "locate-content-drawer", "kind": "localize_only", "description": "the Content Drawer button at the bottom of the window","expect_change": False},
    {"id": "locate-save-all",       "kind": "localize_only", "description": "the Save All icon in the top toolbar",                 "expect_change": False},
    {"id": "locate-outliner-panel", "kind": "localize_only", "description": "the World Outliner panel title",                       "expect_change": False},
    {"id": "locate-details-panel",  "kind": "localize_only", "description": "the Details panel title",                              "expect_change": False},
]


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def _draw_crosshair(img: Image.Image, x: int, y: int) -> Image.Image:
    annotated = img.copy()
    d = ImageDraw.Draw(annotated)
    # Red + cyan crosshair, 24x24 outline.
    r = 12
    for color, off in (("cyan", 1), ("red", 0)):
        d.line([(x - r + off, y), (x + r + off, y)], fill=color, width=2)
        d.line([(x, y - r + off), (x, y + r + off)], fill=color, width=2)
    d.rectangle([x - r, y - r, x + r, y + r], outline="red", width=2)
    return annotated


def _mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    # Average pixel difference across all channels.
    hist = diff.histogram()
    total = 0.0
    count = 0
    for channel_start in (0, 256, 512):
        channel = hist[channel_start:channel_start + 256]
        for value, n in enumerate(channel):
            total += value * n
            count += n
    return total / max(count, 1)


def _run_task(task: dict, client, model: str, window_title: str, out_dir: Path,
              dry_run: bool, verbose: bool) -> dict:
    row = {
        "id": task["id"], "kind": task["kind"], "description": task["description"],
        "t_window_find_ms": 0.0, "t_capture_ms": 0.0, "t_localize_ms": 0.0,
        "t_click_ms": 0.0, "t_total_ms": 0.0,
        "coords": None, "screen_coords": None, "in_bounds": None,
        "visual_change": "N/A", "before_image": None, "after_image": None,
        "error": None,
    }
    task_start = time.perf_counter()
    try:
        if task["kind"] == "key":
            if not HAVE_EXT:
                row["error"] = "skipped (press_key not yet exported)"
            else:
                t0 = time.perf_counter()
                press_key(task["description"])
                row["t_click_ms"] = _ms(t0)
            row["t_total_ms"] = _ms(task_start)
            return row

        t0 = time.perf_counter(); hwnd, _t = find_window(window_title); row["t_window_find_ms"] = _ms(t0)
        t0 = time.perf_counter(); image, (win_left, win_top) = capture(hwnd); row["t_capture_ms"] = _ms(t0)
        t0 = time.perf_counter(); x, y = localize(client, model, image, task["description"]); row["t_localize_ms"] = _ms(t0)

        sx, sy = win_left + x, win_top + y
        row["coords"] = (x, y)
        row["screen_coords"] = (sx, sy)
        row["in_bounds"] = 0 <= x < image.width and 0 <= y < image.height

        before_path = out_dir / f"before-{task['id']}.png"
        _draw_crosshair(image, x, y).save(before_path)
        row["before_image"] = before_path.name

        if task["kind"] == "click" and not dry_run:
            t0 = time.perf_counter(); click_at(sx, sy); row["t_click_ms"] = _ms(t0)
            if task["expect_change"]:
                time.sleep(0.5)
                try:
                    after_img, _ = capture(hwnd)
                    after_path = out_dir / f"after-{task['id']}.png"
                    after_img.save(after_path)
                    row["after_image"] = after_path.name
                    diff = _mean_abs_diff(image, after_img)
                    row["visual_change"] = bool(diff > 1.0)
                    if verbose:
                        print(f"  mean-abs-diff={diff:.3f}")
                except Exception as e:
                    row["visual_change"] = f"capture-failed: {e}"
        elif task["kind"] == "click" and dry_run:
            row["visual_change"] = "dry-run"

        row["t_total_ms"] = _ms(task_start)
    except SystemExit as e:
        row["error"] = str(e)
        row["t_total_ms"] = _ms(task_start)
    except Exception as e:
        if verbose:
            traceback.print_exc()
        row["error"] = f"{type(e).__name__}: {e}"
        row["t_total_ms"] = _ms(task_start)
    return row


def _fmt_coords(c) -> str:
    return f"({c[0]},{c[1]})" if c else "-"


def _fmt_bool(v) -> str:
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return str(v)


def _write_report(rows: list[dict], out_dir: Path, *, window_title: str, hwnd,
                  image_size, model: str, total_s: float) -> Path:
    ok_rows = [r for r in rows if r["error"] is None and r["kind"] != "key"]
    in_bounds = sum(1 for r in ok_rows if r["in_bounds"])
    change_rows = [r for r in rows if r["kind"] == "click"]
    change_ok = sum(1 for r in change_rows if r["visual_change"] is True)

    localize_ms = [r["t_localize_ms"] for r in ok_rows if r["t_localize_ms"] > 0]
    if localize_ms:
        avg = statistics.mean(localize_ms)
        med = statistics.median(localize_ms)
        p95 = sorted(localize_ms)[max(0, int(len(localize_ms) * 0.95) - 1)]
    else:
        avg = med = p95 = 0.0

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hwnd_str = f"0x{hwnd:08x}" if hwnd else "?"
    img_str = f"{image_size[0]}x{image_size[1]}" if image_size else "?"

    lines = [
        f"# Holo3-UE Benchmark - {ts}",
        "",
        f"Window: {window_title} @ {hwnd_str}  |  Image: {img_str}  |  Model: {model}",
        "",
        "## Summary",
        f"- Tasks run: {len(rows)}",
        f"- In-bounds: {in_bounds} / {len(ok_rows)}",
        f"- Visual-change verified: {change_ok} / {len(change_rows)} (of {len(change_rows)} expect_change tasks)",
        f"- Total time: {total_s:.2f} s",
        f"- Avg localize: {avg:.0f} ms  (median {med:.0f}, p95 {p95:.0f})",
        "",
        "## Per-task results",
        "| id | kind | localize ms | coords | in_bounds | visual_change | preview |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["error"]:
            lines.append(f"| {r['id']} | {r['kind']} | - | - | - | - | ERROR: {r['error']} |")
            continue
        preview = f"[png]({r['before_image']})" if r["before_image"] else "-"
        in_b = "yes" if r["in_bounds"] else "no" if r["in_bounds"] is False else "N/A"
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['t_localize_ms']:.0f} | "
            f"{_fmt_coords(r['coords'])} | {in_b} | {_fmt_bool(r['visual_change'])} | {preview} |"
        )
    lines.append("")
    lines.append(f"## Extensions available: {'yes' if HAVE_EXT else 'no'}")
    if not HAVE_EXT:
        skipped = [r["id"] for r in rows if r["kind"] == "key"]
        lines.append(f"Skipped key-press tasks (press_key not importable): {', '.join(skipped) or 'none'}")
    lines.append("")

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> int:
    p = argparse.ArgumentParser(description="Benchmark Holo3-UE clicker against a live Unreal Editor.")
    p.add_argument("--window-title", default=DEFAULT_WINDOW_TITLE)
    p.add_argument("--out-dir", default="bench_out")
    p.add_argument("--tasks", help="comma-separated task ids to filter")
    p.add_argument("--dry-run", action="store_true", help="skip clicks (localize-only)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filter tasks.
    if args.tasks:
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in TASKS if t["id"] in wanted]
        if not tasks:
            print(f"no tasks matched {wanted}; known: {[t['id'] for t in TASKS]}", file=sys.stderr)
            return 2
    else:
        tasks = list(TASKS)

    # Probe the window once up-front so we fail fast with a clean message.
    try:
        hwnd, title = find_window(args.window_title)
    except SystemExit as e:
        print(f"bench_ue: {e}", file=sys.stderr)
        return 1

    # Make API client (unless every selected task is a key-press).
    needs_client = any(t["kind"] != "key" for t in tasks)
    client = None
    model = os.environ.get("HAI_MODEL_NAME", DEFAULT_MODEL)
    if needs_client:
        try:
            client = _make_client()
        except Exception as e:
            print(f"bench_ue: could not make Holo3 client: {e}", file=sys.stderr)
            return 1

    # Probe image size for the header.
    try:
        probe_img, _ = capture(hwnd)
        image_size = probe_img.size
    except Exception:
        image_size = (0, 0)

    print(f"bench_ue: window={title!r} hwnd=0x{hwnd:08x} image={image_size[0]}x{image_size[1]} "
          f"model={model} tasks={len(tasks)} dry_run={args.dry_run}")

    rows: list[dict] = []
    bench_start = time.perf_counter()
    for t in tasks:
        if args.verbose:
            print(f"--- {t['id']} ({t['kind']}): {t['description']}")
        row = _run_task(t, client, model, args.window_title, out_dir,
                        args.dry_run, args.verbose)
        rows.append(row)
        status = f"ERROR: {row['error']}" if row["error"] else f"{row['t_localize_ms']:.0f}ms"
        print(f"  {t['id']}: {status}")
        time.sleep(0.3)
    total_s = time.perf_counter() - bench_start

    # Suppress unused warning; localize_in_window/click_by_description are part
    # of the committed API surface the spec asked us to import from.
    _ = (localize_in_window, click_by_description)

    report_path = _write_report(
        rows, out_dir,
        window_title=title, hwnd=hwnd, image_size=image_size,
        model=model, total_s=total_s,
    )
    print(f"bench_ue: wrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
