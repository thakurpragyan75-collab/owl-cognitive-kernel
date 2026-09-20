"""Explicit repository targeting. The model never chooses the path."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class RepoError(ValueError):
    code = "INVALID_REPOSITORY"


BLOCKED_PREFIXES = (
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/root",
    "/boot",
    "/usr",
    "/bin",
    "/sbin",
    "/var/run",
    "/var/log",
)

SECRET_PARTS = {".ssh", ".gnupg", ".aws", ".kube", ".docker", ".netrc"}


def default_allowed_roots() -> list[Path]:
    roots: list[Path] = []
    raw = os.environ.get("OWL_KERNEL_ALLOWED_ROOTS") or ""
    for part in raw.split(":"):
        p = part.strip()
        if p:
            roots.append(Path(p).expanduser().resolve())
    for extra in ("/tmp", "/var/tmp", "/workspace"):
        pe = Path(extra)
        if pe.exists():
            roots.append(pe.resolve())
    ws = os.environ.get("OWL_KERNEL_WORKSPACE_ROOT")
    if ws:
        roots.append(Path(ws).expanduser().resolve())
    # Kernel checkout itself (for CLI examples), never used as an HTTP default.
    here = Path(__file__).resolve().parents[2]
    roots.append(here)
    return _uniq(roots)


def _uniq(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


@dataclass
class RepoTarget:
    path: Path
    id: str
    label: str
    baseline_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "id": self.id,
            "label": self.label,
            "baseline_hash": self.baseline_hash,
        }


def _inside(child: Path, root: Path) -> bool:
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def _is_secret(resolved: Path) -> bool:
    parts = set(resolved.parts)
    if parts & SECRET_PARTS:
        return True
    home = Path.home().resolve()
    if resolved == home:
        return True
    if str(resolved) in {"/home", "/Users"}:
        return True
    return False


def resolve_repository(
    path: str | Path | None,
    *,
    allowed_roots: list[Path] | None = None,
    workspace_root: str | Path | None = None,
) -> RepoTarget:
    if path is None or str(path).strip() == "":
        raise RepoError("repository.path is required; the kernel will not infer a demo repo")
    raw = Path(str(path)).expanduser()
    if workspace_root and not raw.is_absolute():
        raw = Path(workspace_root).expanduser().resolve() / raw
    if ".." in raw.parts:
        # still resolve, then check roots — but reject explicit traversal in the input
        if any(part == ".." for part in Path(str(path)).parts):
            raise RepoError("path traversal is not allowed")
    try:
        resolved = raw.resolve(strict=False)
    except OSError as e:
        raise RepoError(f"cannot resolve repository path: {e}") from e
    resolved = resolved.resolve()
    text = str(resolved)
    for blocked in BLOCKED_PREFIXES:
        if text == blocked or text.startswith(blocked + "/"):
            raise RepoError(f"repository path is in a blocked system location: {blocked}")
    if _is_secret(resolved):
        raise RepoError("home-directory-wide or secret location is not allowed")
    if not resolved.exists():
        raise RepoError(f"repository does not exist: {resolved}")
    if not resolved.is_dir():
        raise RepoError(f"repository is not a directory: {resolved}")
    roots = allowed_roots if allowed_roots is not None else default_allowed_roots()
    roots = [Path(r).resolve() for r in roots]
    if not any(_inside(resolved, r) for r in roots):
        raise RepoError(f"repository is outside allowed roots: {resolved}")
    label = resolved.name or "repo"
    ident = str(abs(hash(str(resolved))))
    return RepoTarget(path=resolved, id=ident, label=label)
