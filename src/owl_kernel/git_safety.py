from __future__ import annotations

import subprocess
from pathlib import Path


class GitSafetyError(RuntimeError):
    pass


def _run(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if proc.returncode != 0:
        raise GitSafetyError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def snapshot(repo: Path) -> dict:
    if not (repo / ".git").exists():
        return {"git": False}
    branch = _run(repo, "rev-parse", "--abbrev-ref", "HEAD")
    sha = _run(repo, "rev-parse", "HEAD")
    status = _run(repo, "status", "--porcelain")
    return {"git": True, "branch": branch, "sha": sha, "dirty": bool(status), "status": status}


def feature_branch(repo: Path, name: str) -> str:
    snap = snapshot(repo)
    if not snap.get("git"):
        raise GitSafetyError("not a git repo")
    if snap["branch"] == "main" or snap["branch"] == "master":
        _run(repo, "checkout", "-b", name)
    return snapshot(repo)["branch"]


def refuse_force_push() -> None:
    """API surface: callers must never pass --force."""
    raise GitSafetyError("force-push is forbidden")
