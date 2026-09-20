"""Isolated candidate transaction: BASELINE → SNAPSHOT → CANDIDATE → VERIFY → DISCARD.

The original repository is never mutated. Rollback means discarding the copy.
Writes to the original repo are NOT implemented and must go through approval.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .codegraph.index import file_hash


IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".venv", "node_modules", ".pytest_cache")
SKIP = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}


def _keep(p: Path, root: Path) -> bool:
    return not any(part in SKIP for part in p.relative_to(root).parts)


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or not _keep(p, root):
            continue
        h.update(str(p.relative_to(root)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


@dataclass
class Candidate:
    origin: Path
    workspace: Path
    baseline_hash: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    accepted: bool = False
    discarded: bool = False

    def snapshot(self) -> "Candidate":
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        shutil.copytree(self.origin, self.workspace, ignore=IGNORE)
        self.baseline_hash = _tree_hash(self.workspace)
        self.file_hashes = {
            str(p.relative_to(self.workspace)): file_hash(p)
            for p in self.workspace.rglob("*")
            if p.is_file() and _keep(p, self.workspace)
        }
        return self

    def changed_files(self) -> list[str]:
        now = {
            str(p.relative_to(self.workspace)): file_hash(p)
            for p in self.workspace.rglob("*")
            if p.is_file() and _keep(p, self.workspace)
        }
        changed = [k for k, v in now.items() if self.file_hashes.get(k) != v]
        changed += [k for k in self.file_hashes if k not in now]
        return sorted(set(changed))

    def diff(self) -> str:
        lines = []
        for rel in self.changed_files():
            a = self.origin / rel
            b = self.workspace / rel
            old = a.read_text(encoding="utf-8", errors="replace") if a.exists() else ""
            new = b.read_text(encoding="utf-8", errors="replace") if b.exists() else ""
            if old == new:
                continue
            lines.append(f"--- a/{rel}")
            lines.append(f"+++ b/{rel}")
            for ln in new.splitlines():
                if ln not in old.splitlines():
                    lines.append(f"+ {ln}")
            for ln in old.splitlines():
                if ln not in new.splitlines():
                    lines.append(f"- {ln}")
        return "\n".join(lines)

    def discard(self) -> None:
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.discarded = True
        self.accepted = False

    def accept_isolated(self) -> None:
        """Mark verified. Does not copy back onto origin — that needs approval."""
        self.accepted = True
