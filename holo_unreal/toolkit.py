"""Unreal Engine utility toolkit — library + CLI core.

Covers every editor lifecycle op that can be done from the outside:
launch/close, log filtering, error triage, headless commandlets (Fix Up
Redirectors, ResavePackages, cook, full BuildCookRun package), and — the
killer feature — Python execution inside the running editor via the
`PythonScriptPlugin` remote-execution protocol.

Engine detection reads `EngineAssociation` from the `.uproject` and falls
back to the highest installed `C:\\Program Files\\Epic Games\\UE_5.*`.

Every public function returns a plain dict (`{"ok": bool, ...}`) so it
composes cleanly with the CLI, MCP server, and library callers.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._env import default_project, load_env

ENGINE_BASE = Path(os.environ.get("UE_ENGINE_BASE", r"C:\Program Files\Epic Games"))


class UEToolkitError(RuntimeError):
    """Raised on unrecoverable toolkit errors (missing project, engine, etc.)."""


# -------------------------------------------------------- path helpers

def _resolve_project(project: str | os.PathLike | None) -> Path:
    load_env()
    p = project or default_project()
    if not p:
        raise UEToolkitError(
            "no project specified — pass project=..., set UE_PROJECT env var, "
            "or run from the CLI with --project <path.uproject>."
        )
    path = Path(p)
    if not path.exists():
        raise UEToolkitError(f"project not found: {path}")
    return path


def _engine_for(uproject: Path) -> Path:
    try:
        data = json.loads(uproject.read_text())
    except Exception:
        data = {}
    assoc = str(data.get("EngineAssociation", "")).strip()
    if assoc and (ENGINE_BASE / f"UE_{assoc}").is_dir():
        return ENGINE_BASE / f"UE_{assoc}"
    candidates = sorted(
        (p for p in ENGINE_BASE.glob("UE_*") if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        raise UEToolkitError(f"no UE engine found under {ENGINE_BASE}")
    return candidates[0]


def _editor(engine: Path) -> Path:
    return engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"


def _editor_cmd(engine: Path) -> Path:
    return engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"


def _runuat(engine: Path) -> Path:
    return engine / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"


def _remote_exec_dir(engine: Path) -> Path:
    return (
        engine / "Engine" / "Plugins" / "Experimental"
        / "PythonScriptPlugin" / "Content" / "Python"
    )


def _project_log(uproject: Path) -> Path:
    return uproject.parent / "Saved" / "Logs" / f"{uproject.stem}.log"


def _running_pids(exe_name: str = "UnrealEditor.exe") -> list[int]:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}"], text=True,
        )
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == exe_name.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


# ------------------------------------------------------ library surface

def project_info(project: str | os.PathLike | None = None) -> dict:
    """Report project, engine, log path, running pids."""
    p = _resolve_project(project)
    eng = _engine_for(p)
    return {
        "ok": True,
        "project": str(p),
        "project_dir": str(p.parent),
        "project_log": str(_project_log(p)),
        "engine": str(eng),
        "engine_version": eng.name,
        "editor": str(_editor(eng)),
        "editor_cmd": str(_editor_cmd(eng)),
        "runuat": str(_runuat(eng)),
        "running_pids": _running_pids(),
    }


def launch_editor(project: str | os.PathLike | None = None) -> dict:
    """Spawn UnrealEditor.exe with the project (detached)."""
    p = _resolve_project(project)
    eng = _engine_for(p)
    editor = _editor(eng)
    if not editor.exists():
        raise UEToolkitError(f"editor not found: {editor}")
    DETACHED = 0x00000008
    proc = subprocess.Popen([str(editor), str(p)], creationflags=DETACHED)
    return {"ok": True, "pid": proc.pid, "editor": str(editor), "project": str(p)}


def close_editor(*, force: bool = False) -> dict:
    pids = _running_pids()
    if not pids:
        return {"ok": True, "closed": [], "note": "no UnrealEditor.exe running"}
    closed = []
    for pid in pids:
        flag = ["/F"] if force else []
        r = subprocess.run(
            ["taskkill", *flag, "/PID", str(pid)], capture_output=True, text=True,
        )
        closed.append({
            "pid": pid,
            "returncode": r.returncode,
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
        })
    return {"ok": True, "closed": closed}


def read_log(
    project: str | os.PathLike | None = None,
    *,
    grep: str | None = None,
    tail: int = 0,
) -> dict:
    p = _resolve_project(project)
    log = _project_log(p)
    if not log.exists():
        raise UEToolkitError(f"log not found: {log}")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    if grep:
        pat = re.compile(grep, re.IGNORECASE)
        lines = [ln for ln in lines if pat.search(ln)]
    if tail:
        lines = lines[-tail:]
    return {"ok": True, "log": str(log), "lines": lines}


def collect_errors(
    project: str | os.PathLike | None = None,
    *,
    since_session: bool = False,
    top_n: int = 25,
) -> dict:
    p = _resolve_project(project)
    log = _project_log(p)
    if not log.exists():
        raise UEToolkitError(f"log not found: {log}")
    text = log.read_text(encoding="utf-8", errors="replace")
    if since_session:
        for marker in ("LogInit: Display: Starting Game.", "Log file open"):
            idx = text.rfind(marker)
            if idx != -1:
                text = text[idx:]
                break
    err_pat = re.compile(r"(Error:|Fatal:|Assertion failed|Script Msg:|\[Compiler\])")
    lines = [ln for ln in text.splitlines() if err_pat.search(ln)]
    agg: dict[str, int] = {}
    for ln in lines:
        key = re.sub(r"\[\d{4}\.\d{2}\.\d{2}[^\]]*\]\s*", "", ln)
        key = re.sub(r"\[\s*\d+\s*\]\s*", "", key)
        agg[key] = agg.get(key, 0) + 1
    items = sorted(agg.items(), key=lambda kv: -kv[1])
    return {
        "ok": True,
        "log": str(log),
        "total_error_lines": len(lines),
        "unique": len(agg),
        "top": [{"count": c, "message": k} for k, c in items[:top_n]],
    }


def _run_editor_cmd(
    uproject: Path,
    args: list[str],
    *,
    tail_lines: int = 40,
) -> dict:
    eng = _engine_for(uproject)
    cmd = [str(_editor_cmd(eng)), str(uproject), *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "cmd": cmd,
        "stdout_tail": "\n".join(r.stdout.splitlines()[-tail_lines:]),
        "stderr_tail": "\n".join(r.stderr.splitlines()[-tail_lines:]),
    }


def run_commandlet(
    commandlet: str,
    *extra: str,
    project: str | os.PathLike | None = None,
) -> dict:
    """Generic commandlet runner — `UnrealEditor-Cmd.exe <uproject> -run=<name> [args...]`."""
    p = _resolve_project(project)
    return _run_editor_cmd(p, [f"-run={commandlet}", *extra])


def fixup_redirectors(project: str | os.PathLike | None = None) -> dict:
    """Fix Up Redirectors across /Game (ResavePackages -FixupRedirects)."""
    p = _resolve_project(project)
    return _run_editor_cmd(p, ["-run=ResavePackages", "-FixupRedirects", "-Unattended"])


def resave_packages(
    project: str | os.PathLike | None = None,
    *,
    path: str = "",
) -> dict:
    p = _resolve_project(project)
    extra = ["-Unattended"]
    if path:
        extra += [f"-PackageFolder={path}"]
    return _run_editor_cmd(p, ["-run=ResavePackages", *extra])


def cook(
    project: str | os.PathLike | None = None,
    *,
    platform: str = "Windows",
) -> dict:
    p = _resolve_project(project)
    return _run_editor_cmd(p, ["-run=Cook", f"-TargetPlatform={platform}", "-Unattended"], tail_lines=50)


def package(
    project: str | os.PathLike | None = None,
    *,
    platform: str = "Win64",
    config: str = "Development",
    out: str = r"C:\UE_Builds",
) -> dict:
    p = _resolve_project(project)
    eng = _engine_for(p)
    runuat = _runuat(eng)
    if not runuat.exists():
        raise UEToolkitError(f"RunUAT not found: {runuat}")
    cmd = [
        str(runuat), "BuildCookRun",
        f"-project={p}",
        f"-platform={platform}",
        f"-clientconfig={config}",
        "-build", "-cook", "-stage", "-package", "-pak", "-archive",
        f"-archivedirectory={out}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "cmd": cmd,
        "stdout_tail": "\n".join(r.stdout.splitlines()[-60:]),
        "stderr_tail": "\n".join(r.stderr.splitlines()[-60:]),
    }


# ------------------------------- Python remote execution in running editor

def _import_remote_execution(engine: Path):
    d = str(_remote_exec_dir(engine))
    if d not in sys.path:
        sys.path.insert(0, d)
    import remote_execution  # type: ignore
    return remote_execution


def _run_python_remote(engine: Path, code: str, timeout: float = 30.0) -> dict:
    re_mod = _import_remote_execution(engine)
    config = re_mod.RemoteExecutionConfig()
    ex = re_mod.RemoteExecution(config)
    try:
        ex.start()
        deadline = time.time() + 5.0
        while time.time() < deadline and not ex.remote_nodes:
            time.sleep(0.1)
        if not ex.remote_nodes:
            return {
                "ok": False,
                "error": (
                    "no editor nodes found. Run `hue enable-remote` and restart the "
                    "editor, then try again."
                ),
            }
        ex.open_command_connection(ex.remote_nodes)
        result = ex.run_command(
            code,
            unattended=True,
            exec_mode=re_mod.MODE_EXEC_FILE,
            raise_on_failure=False,
        )
        return {"ok": bool(result.get("success")), "result": result}
    finally:
        try:
            ex.stop()
        except Exception:
            pass


def py_in_editor(
    code: str,
    *,
    project: str | os.PathLike | None = None,
    timeout: float = 30.0,
) -> dict:
    """Exec Python in the running editor via PythonScriptPlugin remote_execution."""
    p = _resolve_project(project)
    eng = _engine_for(p)
    return _run_python_remote(eng, code, timeout=timeout)


def py_file_in_editor(
    path: str | os.PathLike,
    *,
    project: str | os.PathLike | None = None,
    timeout: float = 60.0,
) -> dict:
    script = Path(path)
    if not script.exists():
        raise UEToolkitError(f"script not found: {script}")
    code = script.read_text(encoding="utf-8")
    p = _resolve_project(project)
    eng = _engine_for(p)
    return _run_python_remote(eng, code, timeout=timeout)


def enable_remote_execution(project: str | os.PathLike | None = None) -> dict:
    """Write `bRemoteExecution=True` into Config/DefaultEngine.ini AND ensure the
    required plugins (PythonScriptPlugin, EditorScriptingUtilities) are enabled
    in the .uproject. Editor must be restarted for the change to take effect."""
    p = _resolve_project(project)

    # Plugin enablement.
    proj = json.loads(p.read_text())
    plugins = proj.setdefault("Plugins", [])
    names = {pl.get("Name") for pl in plugins}
    plugin_added: list[str] = []
    for need in ["PythonScriptPlugin", "EditorScriptingUtilities"]:
        if need not in names:
            plugins.append({"Name": need, "Enabled": True})
            plugin_added.append(need)
    if plugin_added:
        p.write_text(json.dumps(proj, indent=1) + "\n")

    # INI entry.
    ini = p.parent / "Config" / "DefaultEngine.ini"
    header = "[/Script/PythonScriptPlugin.PythonScriptPluginSettings]"
    entry = "bRemoteExecution=True"
    ini.parent.mkdir(parents=True, exist_ok=True)
    existing = ini.read_text(encoding="utf-8", errors="replace") if ini.exists() else ""
    if entry in existing and header in existing:
        return {
            "ok": True,
            "note": "already enabled",
            "ini": str(ini),
            "plugins_added": plugin_added,
        }
    if header in existing:
        content = re.sub(
            re.escape(header) + r"\s*",
            header + "\n" + entry + "\n",
            existing,
            count=1,
        )
    else:
        sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
        content = existing + sep + header + "\n" + entry + "\n"
    ini.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "ini": str(ini),
        "plugins_added": plugin_added,
        "note": "restart editor for setting to take effect",
    }


def doctor(project: str | os.PathLike | None = None) -> dict:
    """Diagnose all prerequisites — engine, binaries, remote exec, plugins."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    try:
        p = _resolve_project(project)
    except UEToolkitError as exc:
        return {"ok": False, "checks": [{"check": "project", "ok": False, "detail": str(exc)}]}

    check("project exists", p.exists(), str(p))
    try:
        eng = _engine_for(p)
    except UEToolkitError as exc:
        return {
            "ok": False,
            "checks": checks + [{"check": "engine detected", "ok": False, "detail": str(exc)}],
        }
    check("engine detected", eng.exists(), str(eng))
    check("editor binary", _editor(eng).exists(), str(_editor(eng)))
    check("editor-cmd binary", _editor_cmd(eng).exists(), str(_editor_cmd(eng)))
    check("runuat", _runuat(eng).exists(), str(_runuat(eng)))
    check(
        "remote_execution.py",
        (_remote_exec_dir(eng) / "remote_execution.py").exists(),
        str(_remote_exec_dir(eng)),
    )
    check("project log", _project_log(p).exists(), str(_project_log(p)))

    pids = _running_pids()
    check("editor running", bool(pids), f"pids={pids}")

    de = p.parent / "Config" / "DefaultEngine.ini"
    remote_enabled = False
    if de.exists():
        txt = de.read_text(errors="replace")
        remote_enabled = (
            "[/Script/PythonScriptPlugin.PythonScriptPluginSettings]" in txt
            and "bRemoteExecution=True" in txt
        )
    check(
        "python remote execution enabled",
        remote_enabled,
        "run `hue ue enable-remote` then restart editor",
    )

    try:
        proj = json.loads(p.read_text())
    except Exception:
        proj = {}
    plugin_names = {pl.get("Name") for pl in proj.get("Plugins", [])}
    check(
        "PythonScriptPlugin in .uproject",
        "PythonScriptPlugin" in plugin_names,
        f"plugins: {sorted(plugin_names)}",
    )

    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# ------------------------------------------------------- dataclass wrapper

@dataclass
class UEToolkit:
    """Convenience wrapper that binds a project path across all ops."""

    project: str | os.PathLike | None = None

    def info(self) -> dict:
        return project_info(self.project)

    def launch(self) -> dict:
        return launch_editor(self.project)

    def close(self, *, force: bool = False) -> dict:
        return close_editor(force=force)

    def log(self, *, grep: str | None = None, tail: int = 0) -> dict:
        return read_log(self.project, grep=grep, tail=tail)

    def errors(self, *, since_session: bool = False, top_n: int = 25) -> dict:
        return collect_errors(self.project, since_session=since_session, top_n=top_n)

    def headless(self, commandlet: str, *extra: str) -> dict:
        return run_commandlet(commandlet, *extra, project=self.project)

    def fixup(self) -> dict:
        return fixup_redirectors(self.project)

    def resave(self, *, path: str = "") -> dict:
        return resave_packages(self.project, path=path)

    def py(self, code: str, *, timeout: float = 30.0) -> dict:
        return py_in_editor(code, project=self.project, timeout=timeout)

    def pyfile(self, path: str | os.PathLike, *, timeout: float = 60.0) -> dict:
        return py_file_in_editor(path, project=self.project, timeout=timeout)

    def cook(self, *, platform: str = "Windows") -> dict:
        return cook(self.project, platform=platform)

    def package(
        self,
        *,
        platform: str = "Win64",
        config: str = "Development",
        out: str = r"C:\UE_Builds",
    ) -> dict:
        return package(self.project, platform=platform, config=config, out=out)

    def enable_remote(self) -> dict:
        return enable_remote_execution(self.project)

    def doctor(self) -> dict:
        return doctor(self.project)


__all__ = [
    "UEToolkit",
    "UEToolkitError",
    "close_editor",
    "collect_errors",
    "cook",
    "doctor",
    "enable_remote_execution",
    "fixup_redirectors",
    "launch_editor",
    "package",
    "project_info",
    "py_in_editor",
    "py_file_in_editor",
    "read_log",
    "resave_packages",
    "run_commandlet",
]
