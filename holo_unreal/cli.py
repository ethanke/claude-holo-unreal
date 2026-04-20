"""Unified CLI for claude-holo-unreal.

Every subcommand emits either a human-readable line or a single JSON line on
stdout. Scripts should parse JSON (`--json` is the default for toolkit ops);
humans should look at the text.

Top-level groups
  ue <subcommand>   — Unreal Engine toolkit (launch, log, py, ...)
  click <desc>      — Holo3-grounded click in the UE window
  right-click <desc>
  double-click <desc>
  type <desc> <text>
  press <combo>
  locate <desc>     — dry-run: localize + optional annotated screenshot
  list-windows      — enumerate visible top-level windows
  mcp               — run the MCP server (stdio)
  skills install    — copy shipped skills into ~/.claude/skills/
  info              — print package version + backend keys
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from ._env import default_project, hai_api_key, load_env
from .toolkit import (
    UEToolkitError,
    close_editor,
    collect_errors,
    cook,
    doctor,
    enable_remote_execution,
    fixup_redirectors,
    launch_editor,
    package,
    project_info,
    py_file_in_editor,
    py_in_editor,
    read_log,
    resave_packages,
    run_commandlet,
)


def _emit(obj) -> None:
    print(json.dumps(obj, default=str, ensure_ascii=False))


def _fail(msg: str, code: int = 1, **extra) -> None:
    _emit({"ok": False, "error": msg, **extra})
    sys.exit(code)


# ----------------------------------------------------------------- ue group

def _cmd_ue_info(a) -> None:
    _emit(project_info(a.project))


def _cmd_ue_launch(a) -> None:
    _emit(launch_editor(a.project))


def _cmd_ue_close(a) -> None:
    _emit(close_editor(force=a.force))


def _cmd_ue_log(a) -> None:
    out = read_log(a.project, grep=a.grep, tail=a.tail)
    for ln in out["lines"]:
        print(ln)


def _cmd_ue_errors(a) -> None:
    _emit(collect_errors(a.project, since_session=a.since_session, top_n=a.top))


def _cmd_ue_headless(a) -> None:
    _emit(run_commandlet(a.commandlet, *a.extra, project=a.project))


def _cmd_ue_fixup(a) -> None:
    _emit(fixup_redirectors(a.project))


def _cmd_ue_resave(a) -> None:
    _emit(resave_packages(a.project, path=a.path))


def _cmd_ue_py(a) -> None:
    _emit(py_in_editor(a.code, project=a.project, timeout=a.timeout))


def _cmd_ue_pyfile(a) -> None:
    _emit(py_file_in_editor(a.path, project=a.project, timeout=a.timeout))


def _cmd_ue_cook(a) -> None:
    _emit(cook(a.project, platform=a.platform))


def _cmd_ue_package(a) -> None:
    _emit(package(a.project, platform=a.platform, config=a.config, out=a.out))


def _cmd_ue_enable_remote(a) -> None:
    _emit(enable_remote_execution(a.project))


def _cmd_ue_doctor(a) -> None:
    _emit(doctor(a.project))


# -------------------------------------------------------- vision / click ops

def _cmd_list_windows(a) -> None:
    from .vision import list_windows

    for hwnd, title in list_windows():
        print(f"0x{hwnd:08x}  {title}")


def _cmd_locate(a) -> None:
    from PIL import ImageDraw

    from .vision import (
        _make_client,
        capture,
        find_window,
        localize,
    )
    from ._env import default_window_title, hai_model

    if not hai_api_key():
        _fail("HAI_API_KEY not set — put it in .env or export it first.")
    title = a.window_title or default_window_title()
    hwnd, found_title = find_window(title)
    image, (left, top) = capture(hwnd)
    client = _make_client()
    model = a.model or hai_model()
    x, y = localize(client, model, image, a.description, a.temperature)
    result = {
        "ok": True,
        "window": found_title,
        "window_origin": [left, top],
        "image": [image.width, image.height],
        "window_xy": [x, y],
        "screen_xy": [left + x, top + y],
    }
    if a.save:
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        draw.line([(x - 15, y), (x + 15, y)], fill="red", width=3)
        draw.line([(x, y - 15), (x, y + 15)], fill="red", width=3)
        draw.ellipse([x - 10, y - 10, x + 10, y + 10], outline="red", width=2)
        annotated.save(a.save)
        result["saved"] = a.save
    _emit(result)


def _cmd_click(a) -> None:
    from .vision import click_by_description

    if not hai_api_key():
        _fail("HAI_API_KEY not set — put it in .env or export it first.")
    if not a.yes:
        print(f"clicking in 1s (Ctrl+C to cancel)...")
        time.sleep(1.0)
    sx, sy = click_by_description(
        a.description,
        window_title=a.window_title,
        model=a.model,
        temperature=a.temperature,
        dry_run=a.dry_run,
    )
    _emit({"ok": True, "screen_xy": [sx, sy], "dry_run": a.dry_run})


def _cmd_right_click(a) -> None:
    from .vision import right_click_by_description

    if not hai_api_key():
        _fail("HAI_API_KEY not set — put it in .env or export it first.")
    if not a.yes:
        time.sleep(1.0)
    sx, sy = right_click_by_description(
        a.description,
        window_title=a.window_title,
        model=a.model,
        temperature=a.temperature,
        dry_run=a.dry_run,
    )
    _emit({"ok": True, "screen_xy": [sx, sy], "dry_run": a.dry_run})


def _cmd_double_click(a) -> None:
    from .vision import double_click_by_description

    if not hai_api_key():
        _fail("HAI_API_KEY not set — put it in .env or export it first.")
    if not a.yes:
        time.sleep(1.0)
    sx, sy = double_click_by_description(
        a.description,
        window_title=a.window_title,
        model=a.model,
        temperature=a.temperature,
        dry_run=a.dry_run,
    )
    _emit({"ok": True, "screen_xy": [sx, sy], "dry_run": a.dry_run})


def _cmd_type(a) -> None:
    from .vision import type_into

    if not hai_api_key():
        _fail("HAI_API_KEY not set — put it in .env or export it first.")
    if not a.yes:
        time.sleep(1.0)
    sx, sy = type_into(
        a.description,
        a.text,
        window_title=a.window_title,
        model=a.model,
        dry_run=a.dry_run,
    )
    _emit({"ok": True, "screen_xy": [sx, sy], "typed": len(a.text), "dry_run": a.dry_run})


def _cmd_press(a) -> None:
    from .vision import press_chord

    if a.dry_run:
        _emit({"ok": True, "dry_run": True, "combo": a.combo})
        return
    if not a.yes:
        time.sleep(0.3)
    press_chord(a.combo)
    _emit({"ok": True, "combo": a.combo})


def _cmd_focus(a) -> None:
    from .focus import focus_ue

    ok = focus_ue(park_mouse=not a.no_park)
    _emit({"ok": ok})


# -------------------------------------------------------------- mcp + skills

def _cmd_mcp(a) -> None:
    from .mcp_server import main as mcp_main

    mcp_main()


def _shipped_skills_dir() -> Path | None:
    """Locate the shipped skills directory — works for both pip-installed wheels
    and editable source checkouts."""
    # Preferred: bundled inside the package (works after `pip install`).
    inside = Path(__file__).resolve().parent / "skills"
    if inside.is_dir():
        return inside
    # Fallback: legacy repo-root layout (old clones).
    outside = Path(__file__).resolve().parent.parent / "skills"
    if outside.is_dir():
        return outside
    return None


def _install_skills(target: Path, *, force: bool) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    src_root = _shipped_skills_dir()
    if src_root is None:
        return {
            "ok": False,
            "error": "shipped skills dir not found",
            "target": str(target),
        }
    installed: list[str] = []
    skipped: list[str] = []
    for skill_dir in sorted(src_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        dest = target / skill_dir.name
        if dest.exists() and not force:
            skipped.append(str(dest))
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_dir, dest)
        installed.append(str(dest))
    return {
        "ok": True,
        "installed": installed,
        "skipped": skipped,
        "target": str(target),
        "source": str(src_root),
    }


def _cmd_skills_install(a) -> None:
    target = Path(a.target).expanduser().resolve()
    _emit(_install_skills(target, force=a.force))


def _find_claude_cli() -> str | None:
    """Locate the Claude Code CLI on PATH, including the common ~/.local/bin
    and %APPDATA%\\npm fallback locations shells sometimes miss."""
    exe = shutil.which("claude")
    if exe:
        return exe
    candidates = [
        Path.home() / ".local" / "bin" / "claude",
        Path.home() / ".local" / "bin" / "claude.exe",
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


MCP_SERVER_NAME = "holo-unreal"


def _mcp_is_registered(claude_exe: str) -> bool:
    try:
        r = subprocess.run(
            [claude_exe, "mcp", "list"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return False
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if line.strip().startswith(f"{MCP_SERVER_NAME}:") or line.strip().startswith(f"{MCP_SERVER_NAME} "):
            return True
    return False


def _register_mcp(claude_exe: str, *, scope: str, force: bool) -> dict:
    existed = _mcp_is_registered(claude_exe)
    if existed and not force:
        return {"ok": True, "status": "already-registered", "name": MCP_SERVER_NAME}
    if existed and force:
        subprocess.run(
            [claude_exe, "mcp", "remove", MCP_SERVER_NAME],
            capture_output=True, text=True,
        )
    cmd = [
        claude_exe, "mcp", "add", "-s", scope, MCP_SERVER_NAME,
        "--", sys.executable, "-m", "holo_unreal.mcp_server",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {
            "ok": False,
            "status": "add-failed",
            "returncode": r.returncode,
            "stderr": r.stderr.strip(),
            "cmd": cmd,
        }
    return {
        "ok": True,
        "status": "registered",
        "name": MCP_SERVER_NAME,
        "scope": scope,
        "command": f"{sys.executable} -m holo_unreal.mcp_server",
    }


def _bootstrap(*, scope: str, skip_skills: bool, skip_mcp: bool, force: bool) -> dict:
    load_env()
    report: dict = {
        "ok": True,
        "version": __version__,
        "hai_api_key_set": bool(hai_api_key()),
        "default_project": default_project(),
    }

    if not skip_skills:
        target = Path.home() / ".claude" / "skills"
        report["skills"] = _install_skills(target, force=force)
        if not report["skills"]["ok"]:
            report["ok"] = False

    claude_exe = _find_claude_cli()
    report["claude_cli"] = claude_exe

    if not skip_mcp:
        if claude_exe is None:
            report["mcp"] = {
                "ok": False,
                "status": "claude-not-found",
                "hint": "Install Claude Code from https://claude.com/claude-code",
            }
            report["ok"] = False
        else:
            report["mcp"] = _register_mcp(claude_exe, scope=scope, force=force)
            if not report["mcp"]["ok"]:
                report["ok"] = False

    return report


def _cmd_setup(a) -> None:
    """Install skills + register MCP; don't launch Claude Code."""
    report = _bootstrap(
        scope=a.scope,
        skip_skills=a.no_skills,
        skip_mcp=a.no_mcp,
        force=a.force,
    )
    _emit(report)
    if not report["ok"]:
        sys.exit(1)


def _cmd_claude(a) -> None:
    """Set up skills + MCP, then exec the Claude Code CLI."""
    # Bootstrap (logs human-readable status lines to stderr, then one JSON
    # summary before handing off).
    report = _bootstrap(
        scope=a.scope,
        skip_skills=a.no_skills,
        skip_mcp=a.no_mcp,
        force=a.force,
    )

    # Pretty-print bootstrap status to stderr so stdout stays clean for `claude`.
    def _say(msg: str) -> None:
        print(f"[holo-unreal] {msg}", file=sys.stderr)

    _say(f"version {report['version']}  |  HAI_API_KEY {'set' if report['hai_api_key_set'] else 'MISSING'}")
    skills = report.get("skills")
    if skills:
        if skills["ok"]:
            if skills["installed"]:
                _say(f"installed skills: {', '.join(Path(p).name for p in skills['installed'])}")
            if skills["skipped"]:
                _say(f"skills already present: {', '.join(Path(p).name for p in skills['skipped'])}")
        else:
            _say(f"skills install FAILED: {skills.get('error')}")
    mcp = report.get("mcp")
    if mcp:
        if mcp["ok"]:
            _say(f"MCP server 'holo-unreal': {mcp['status']}")
        else:
            _say(f"MCP setup FAILED ({mcp.get('status')}): {mcp.get('stderr') or mcp.get('hint')}")

    claude_exe = report.get("claude_cli")
    if claude_exe is None:
        _fail(
            "Claude Code CLI not found on PATH. Install from https://claude.com/claude-code, "
            "then re-run `hue claude`."
        )

    if not report["hai_api_key_set"]:
        _say(
            "WARNING: HAI_API_KEY not set — ue_click/ue_locate/ue_type will error. "
            "Put it in .env or export it before using vision tools."
        )

    # Launch claude, inheriting the current terminal (interactive session).
    # Strip any leading `--` separator the argv normalizer may have injected.
    extra = list(a.extra or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    _say(f"launching: {claude_exe} {' '.join(extra)}")
    try:
        r = subprocess.run([claude_exe, *extra])
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(r.returncode)


def _cmd_info(a) -> None:
    load_env()
    _emit({
        "ok": True,
        "version": __version__,
        "hai_api_key_set": bool(hai_api_key()),
        "default_project": default_project(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "claude_cli": _find_claude_cli(),
        "shipped_skills_dir": str(_shipped_skills_dir()) if _shipped_skills_dir() else None,
    })


# ----------------------------------------------------------------- parser

def _add_project_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--project",
        help="path to .uproject (default: $UE_PROJECT)",
        default=None,
    )


def _add_vision_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--window-title", default=None, help="substring of UE window title")
    p.add_argument("--model", default=None, help="override HAI_MODEL_NAME")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--dry-run", action="store_true", help="don't click/type/press")
    p.add_argument("-y", "--yes", action="store_true", help="skip the 1s countdown")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="holo-unreal",
        description="Unreal Engine copilot for Claude Code — UE toolkit + Holo3 vision.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sp = p.add_subparsers(dest="cmd", required=True)

    # ue <sub>
    ue = sp.add_parser("ue", help="Unreal Engine toolkit")
    ue_sp = ue.add_subparsers(dest="ue_cmd", required=True)

    s = ue_sp.add_parser("info", help="project + engine paths + running state")
    _add_project_arg(s)
    s.set_defaults(func=_cmd_ue_info)

    s = ue_sp.add_parser("launch", help="launch editor with project (detached)")
    _add_project_arg(s)
    s.set_defaults(func=_cmd_ue_launch)

    s = ue_sp.add_parser("close", help="close running editor")
    _add_project_arg(s)
    s.add_argument("--force", action="store_true", help="taskkill /F")
    s.set_defaults(func=_cmd_ue_close)

    s = ue_sp.add_parser("log", help="read current project log")
    _add_project_arg(s)
    s.add_argument("--grep", default=None, help="regex filter (case-insensitive)")
    s.add_argument("--tail", type=int, default=0, help="last N matching lines")
    s.set_defaults(func=_cmd_ue_log)

    s = ue_sp.add_parser("errors", help="extract + aggregate error lines from log")
    _add_project_arg(s)
    s.add_argument("--since-session", action="store_true")
    s.add_argument("--top", type=int, default=25)
    s.set_defaults(func=_cmd_ue_errors)

    s = ue_sp.add_parser("headless", help="run UnrealEditor-Cmd commandlet")
    _add_project_arg(s)
    s.add_argument("commandlet")
    s.add_argument("extra", nargs=argparse.REMAINDER)
    s.set_defaults(func=_cmd_ue_headless)

    s = ue_sp.add_parser("fixup", help="Fix Up Redirectors (ResavePackages -FixupRedirects)")
    _add_project_arg(s)
    s.set_defaults(func=_cmd_ue_fixup)

    s = ue_sp.add_parser("resave", help="resave packages")
    _add_project_arg(s)
    s.add_argument("--path", default="", help="/Game subfolder; blank = all")
    s.set_defaults(func=_cmd_ue_resave)

    s = ue_sp.add_parser("py", help="exec Python in running editor")
    _add_project_arg(s)
    s.add_argument("code")
    s.add_argument("--timeout", type=float, default=30.0)
    s.set_defaults(func=_cmd_ue_py)

    s = ue_sp.add_parser("pyfile", help="exec Python file in running editor")
    _add_project_arg(s)
    s.add_argument("path")
    s.add_argument("--timeout", type=float, default=60.0)
    s.set_defaults(func=_cmd_ue_pyfile)

    s = ue_sp.add_parser("cook", help="cook content for platform")
    _add_project_arg(s)
    s.add_argument("--platform", default="Windows")
    s.set_defaults(func=_cmd_ue_cook)

    s = ue_sp.add_parser("package", help="full BuildCookRun via RunUAT")
    _add_project_arg(s)
    s.add_argument("--platform", default="Win64")
    s.add_argument("--config", default="Development",
                   choices=["Development", "Shipping", "Debug", "Test"])
    s.add_argument("--out", default=r"C:\UE_Builds")
    s.set_defaults(func=_cmd_ue_package)

    s = ue_sp.add_parser("enable-remote",
                         help="write bRemoteExecution=True + enable python plugins")
    _add_project_arg(s)
    s.set_defaults(func=_cmd_ue_enable_remote)

    s = ue_sp.add_parser("doctor", help="diagnose setup")
    _add_project_arg(s)
    s.set_defaults(func=_cmd_ue_doctor)

    # vision group (flat, directly under holo-unreal)
    s = sp.add_parser("list-windows", help="enumerate visible top-level windows")
    s.set_defaults(func=_cmd_list_windows)

    s = sp.add_parser("locate", help="dry-run: localize a described element")
    s.add_argument("description")
    _add_vision_args(s)
    s.add_argument("--save", metavar="PATH", help="save annotated screenshot")
    s.set_defaults(func=_cmd_locate)

    s = sp.add_parser("click", help="Holo3-grounded left click")
    s.add_argument("description")
    _add_vision_args(s)
    s.set_defaults(func=_cmd_click)

    s = sp.add_parser("right-click", help="Holo3-grounded right click")
    s.add_argument("description")
    _add_vision_args(s)
    s.set_defaults(func=_cmd_right_click)

    s = sp.add_parser("double-click", help="Holo3-grounded double click")
    s.add_argument("description")
    _add_vision_args(s)
    s.set_defaults(func=_cmd_double_click)

    s = sp.add_parser("type", help="click described field then type")
    s.add_argument("description")
    s.add_argument("text")
    _add_vision_args(s)
    s.set_defaults(func=_cmd_type)

    s = sp.add_parser("press", help="press a key chord (no click)")
    s.add_argument("combo", help="e.g. 'ctrl+s', 'f5', 'enter'")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=_cmd_press)

    s = sp.add_parser("focus", help="bring the UE editor window to the foreground")
    s.add_argument("--no-park", action="store_true", help="skip mouse-park")
    s.set_defaults(func=_cmd_focus)

    # MCP + skills + info
    s = sp.add_parser("mcp", help="run the holo-unreal MCP server over stdio")
    s.set_defaults(func=_cmd_mcp)

    sk = sp.add_parser("skills", help="manage Claude Code skill files")
    sk_sp = sk.add_subparsers(dest="skills_cmd", required=True)
    s = sk_sp.add_parser("install", help="copy shipped skills to ~/.claude/skills/")
    s.add_argument(
        "--target",
        default=str(Path.home() / ".claude" / "skills"),
        help="destination dir (default: ~/.claude/skills)",
    )
    s.add_argument("--force", action="store_true", help="overwrite existing skill dirs")
    s.set_defaults(func=_cmd_skills_install)

    # One-shot bootstrap: install skills + register MCP + launch Claude Code.
    s = sp.add_parser(
        "claude",
        help="install skills + register MCP server, then launch Claude Code",
    )
    s.add_argument("--scope", default="user", choices=["user", "project", "local"],
                   help="MCP server scope (default: user)")
    s.add_argument("--no-skills", action="store_true",
                   help="skip skill install step")
    s.add_argument("--no-mcp", action="store_true",
                   help="skip MCP server registration step")
    s.add_argument("--force", action="store_true",
                   help="re-install skills and re-register MCP even if already present")
    s.add_argument("extra", nargs=argparse.REMAINDER,
                   help="extra args passed through to `claude` (use -- to separate)")
    s.set_defaults(func=_cmd_claude)

    s = sp.add_parser(
        "setup",
        help="install skills + register MCP server (no launch)",
    )
    s.add_argument("--scope", default="user", choices=["user", "project", "local"])
    s.add_argument("--no-skills", action="store_true")
    s.add_argument("--no-mcp", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=_cmd_setup)

    s = sp.add_parser("info", help="package version + backend keys")
    s.set_defaults(func=_cmd_info)

    return p


KNOWN_SUBCOMMANDS = {
    "ue", "list-windows", "locate", "click", "right-click", "double-click",
    "type", "press", "focus", "mcp", "skills", "claude", "setup", "info",
}
TOP_LEVEL_OPTIONS = {"-h", "--help", "--version"}

# Flags the `claude` subcommand owns itself (vs. pass-through to Claude Code).
_CLAUDE_OWN_FLAGS_WITH_ARG = {"--scope"}
_CLAUDE_OWN_FLAGS_BOOL = {"--no-skills", "--no-mcp", "--force"}


def _shorthand_claude(argv: list[str]) -> int:
    """Route bare args straight to `claude` with defaults for our own flags.

    Makes `python -m holo_unreal` and `python -m holo_unreal --foo` both work:
    the former launches a plain Claude Code session, the latter passes `--foo`
    through to `claude`.
    """
    class _NS:
        scope = "user"
        no_skills = False
        no_mcp = False
        force = False

    ns = _NS()
    ns.extra = list(argv)
    _cmd_claude(ns)
    return 0


def _normalize_claude_argv(argv: list[str]) -> list[str]:
    """For explicit `claude` subcommand: split our flags from Claude Code
    pass-through so argparse's REMAINDER works correctly.

    Example:
        ["claude", "--force", "--dangerously-skip-permissions"]
      → ["claude", "--force", "--", "--dangerously-skip-permissions"]
    """
    rest = argv[1:]
    our: list[str] = []
    passthrough: list[str] = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in ("--help", "-h"):
            our.append(tok)
            i += 1
        elif tok == "--":
            passthrough.extend(rest[i + 1:])
            break
        elif tok in _CLAUDE_OWN_FLAGS_WITH_ARG:
            if i + 1 < len(rest):
                our.extend([tok, rest[i + 1]])
                i += 2
            else:
                our.append(tok)
                i += 1
        elif tok in _CLAUDE_OWN_FLAGS_BOOL:
            our.append(tok)
            i += 1
        else:
            # Anything else → pass-through to Claude Code (stop parsing ours).
            passthrough.extend(rest[i:])
            break
    if passthrough:
        return ["claude"] + our + ["--"] + passthrough
    return argv


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Bare invocation or unknown first token → treat as `claude` shorthand.
    if not argv:
        return _shorthand_claude([])
    if argv[0] not in KNOWN_SUBCOMMANDS and argv[0] not in TOP_LEVEL_OPTIONS:
        return _shorthand_claude(argv)

    # Explicit `claude` subcommand: split our flags from pass-through before
    # argparse sees them (REMAINDER doesn't capture bare flags).
    if argv[0] == "claude":
        argv = _normalize_claude_argv(argv)

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except UEToolkitError as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        _fail("interrupted", code=130)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
