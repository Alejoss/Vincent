"""Run Vincent scripts as subprocesses with a single-writer lock."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.mcp.paths import JOBS_DIR, LOG_DIR, PROJECT_ROOT, SCRIPTS_DIR, python_executable

LOCK_PATH = JOBS_DIR / "vincent_jobs.lock"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock() -> Optional[dict[str, Any]]:
    if not LOCK_PATH.is_file():
        return None
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pid = int(data.get("pid") or 0)
    if not _process_alive(pid):
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
        return None
    return data


def acquire_lock(job: str) -> tuple[bool, str]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    existing = _read_lock()
    if existing:
        return (
            False,
            f"Another Vincent job is running: {existing.get('job')} "
            f"(pid={existing.get('pid')}, started={existing.get('started_at')}).",
        )
    payload = {"job": job, "pid": os.getpid(), "started_at": _now()}
    LOCK_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True, ""


def release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def log_tail(path: Path, *, lines: int = 40) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = text.splitlines()
    return "\n".join(parts[-max(1, lines) :])


def run_script(
    job: str,
    script_name: str,
    args: list[str],
    *,
    wait: bool = True,
    timeout_s: int = 1800,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run ``scripts/<script_name>`` with the Vincent venv Python."""
    ok, reason = acquire_lock(job)
    if not ok:
        return {"ok": False, "error": reason, "job": job}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"mcp_{job}_{stamp}.log"
    latest = LOG_DIR / f"mcp_{job}_latest.log"
    script = PROJECT_ROOT / "scripts" / script_name
    if not script.is_file():
        release_lock()
        return {"ok": False, "error": f"Script not found: {script}", "job": job}

    argv = [python_executable(), str(script), *args]
    header = (
        f"job={job} dry_run={dry_run} wait={wait}\n"
        f"cwd={PROJECT_ROOT}\n"
        f"cmd={' '.join(argv)}\n"
        f"started={_now()}\n\n"
    )
    log_path.write_text(header, encoding="utf-8")

    creationflags = 0
    start_new_session = False
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if not wait:
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        start_new_session = not wait

    try:
        handle = log_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(
            argv,
            cwd=str(PROJECT_ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        handle.close()
        if not wait:
            LOCK_PATH.write_text(
                json.dumps(
                    {
                        "job": job,
                        "pid": proc.pid,
                        "started_at": _now(),
                        "log": str(log_path),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            latest.write_text(log_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            return {
                "ok": True,
                "started": True,
                "waited": False,
                "job": job,
                "pid": proc.pid,
                "log_path": str(log_path),
                "latest_log": str(latest),
                "dry_run": dry_run,
                "message": "Job started in the background. Check log_path for progress.",
            }

        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"Timed out after {timeout_s}s (pid={proc.pid} still running).",
                "job": job,
                "pid": proc.pid,
                "log_path": str(log_path),
                "log_tail": log_tail(log_path),
                "dry_run": dry_run,
            }
        latest.write_text(log_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return {
            "ok": rc == 0,
            "exit_code": rc,
            "waited": True,
            "job": job,
            "pid": proc.pid,
            "log_path": str(log_path),
            "latest_log": str(latest),
            "log_tail": log_tail(log_path),
            "dry_run": dry_run,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "job": job, "log_path": str(log_path)}
    finally:
        if wait:
            release_lock()


def run_productivity_steps(*, wait: bool, dry_run: bool, timeout_s: int = 1800) -> dict[str, Any]:
    """Slack → Obsidian → classify → Notion (same three Python steps as the .bat)."""
    extra = ["--dry-run"] if dry_run else []
    steps = [
        ("slack_inbox", "sync_slack_inbox_to_obsidian.py", ["--days", "3", *extra]),
        ("classify", "classify_slack_input_with_ollama.py", ["--reclassify", *extra]),
        ("notion_sync", "sync_productivity_obsidian_to_notion.py", extra),
    ]
    if not wait:
        # One wrapper: run the three steps sequentially in a tiny python -c is messy.
        # Chain via the first script wait=False only for the whole sequence by
        # launching a helper argv: python -c isn't needed — use a single Popen
        # of a joined command through the first available shell.
        return _run_productivity_chain(wait=False, dry_run=dry_run, timeout_s=timeout_s)

    results = []
    for name, script, args in steps:
        result = run_script(f"productivity_{name}", script, args, wait=True, timeout_s=timeout_s, dry_run=dry_run)
        results.append(result)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": f"Productivity pipeline stopped at {name}.",
                "failed_step": name,
                "steps": results,
            }
    return {"ok": True, "steps": results, "dry_run": dry_run}


def _run_productivity_chain(*, wait: bool, dry_run: bool, timeout_s: int) -> dict[str, Any]:
    ok, reason = acquire_lock("productivity_pipeline")
    if not ok:
        return {"ok": False, "error": reason, "job": "productivity_pipeline"}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"mcp_productivity_pipeline_{stamp}.log"
    latest = LOG_DIR / "mcp_productivity_pipeline_latest.log"
    py = python_executable()
    extra = " --dry-run" if dry_run else ""
    commands = [
        f'"{py}" "{SCRIPTS_DIR / "sync_slack_inbox_to_obsidian.py"}" --days 3{extra}',
        f'"{py}" "{SCRIPTS_DIR / "classify_slack_input_with_ollama.py"}" --reclassify{extra}',
        f'"{py}" "{SCRIPTS_DIR / "sync_productivity_obsidian_to_notion.py"}"{extra}',
    ]

    if sys.platform == "win32":
        chain = " && ".join(commands)
        argv = ["cmd.exe", "/c", chain]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if not wait:
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        start_new_session = False
    else:
        chain = " && ".join(commands)
        argv = ["/bin/bash", "-lc", chain]
        creationflags = 0
        start_new_session = not wait

    log_path.write_text(
        f"job=productivity_pipeline dry_run={dry_run}\ncmd={chain}\nstarted={_now()}\n\n",
        encoding="utf-8",
    )
    try:
        handle = log_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(
            argv,
            cwd=str(PROJECT_ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        handle.close()
        if not wait:
            LOCK_PATH.write_text(
                json.dumps(
                    {
                        "job": "productivity_pipeline",
                        "pid": proc.pid,
                        "started_at": _now(),
                        "log": str(log_path),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            latest.write_text(log_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            return {
                "ok": True,
                "started": True,
                "waited": False,
                "job": "productivity_pipeline",
                "pid": proc.pid,
                "log_path": str(log_path),
                "latest_log": str(latest),
                "dry_run": dry_run,
            }
        rc = proc.wait(timeout=timeout_s)
        latest.write_text(log_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return {
            "ok": rc == 0,
            "exit_code": rc,
            "waited": True,
            "job": "productivity_pipeline",
            "log_path": str(log_path),
            "log_tail": log_tail(log_path),
            "dry_run": dry_run,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Timed out after {timeout_s}s",
            "job": "productivity_pipeline",
            "log_path": str(log_path),
            "log_tail": log_tail(log_path),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "job": "productivity_pipeline"}
    finally:
        if wait:
            release_lock()


