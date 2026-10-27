"""Audit trail for pricing runs.

Each run writes a manifest beside its outputs and appends one line to
runs/audit_log.jsonl. The manifest pins everything needed to reproduce the
numbers: code version and git commit, index version, SHA-256 of every config
file and of the raw rainfall input, and the SHA-256 of results.json.
"""
from __future__ import annotations

import hashlib
import json
import platform
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import __version__


def git_state(repo: Path) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=repo,
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo,
                                    capture_output=True, text=True, check=True).stdout.strip())
        return {"commit": commit, "dirty": dirty}
    except Exception:
        return {"commit": "none", "dirty": True}


def new_run_id(ward_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{ward_id}_{secrets.token_hex(3)}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_manifest(run_id: str, command: str, repo: Path) -> dict:
    import numpy, pandas, scipy  # noqa: E401  (versions only)
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": command,
        "package_version": __version__,
        "git": git_state(repo),
        "python": platform.python_version(),
        "libraries": {"numpy": numpy.__version__, "pandas": pandas.__version__, "scipy": scipy.__version__},
    }


def append_audit_log(runs_dir: Path, manifest: dict) -> None:
    keep = ("run_id", "created_at", "command", "ward_id", "rainfall_source", "index_version",
            "git", "config_sha256", "results_sha256")
    line = {k: manifest.get(k) for k in keep}
    line["rainfall_sha256"] = manifest.get("rainfall", {}).get("sha256")
    with (runs_dir / "audit_log.jsonl").open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
