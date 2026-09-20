"""Isolated candidate: ORIGIN → SNAPSHOT → VERIFY → APPROVAL → READY_FOR_PROMOTION | DISCARD.

The original repository is never mutated in this pass. Promotion is prepared, not applied.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .codegraph.index import file_hash


IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".venv", "node_modules", ".pytest_cache")
SKIP = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}


class CandidateState(str, Enum):
    ORIGIN_DISCOVERED = "ORIGIN_DISCOVERED"
    BASELINED = "BASELINED"
    SNAPSHOTTED = "SNAPSHOTTED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    READY_FOR_PROMOTION = "READY_FOR_PROMOTION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DISCARDED = "DISCARDED"
    PROMOTION_REJECTED = "PROMOTION_REJECTED"


def _keep(p: Path, root: Path) -> bool:
    return not any(part in SKIP for part in p.relative_to(root).parts)


def tree_hash(root: Path) -> str:
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
    origin_hash: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    state: CandidateState = CandidateState.ORIGIN_DISCOVERED
    accepted: bool = False
    discarded: bool = False
    approved_by: str = ""

    def snapshot(self) -> "Candidate":
        self.state = CandidateState.ORIGIN_DISCOVERED
        self.origin_hash = tree_hash(self.origin)
        self.state = CandidateState.BASELINED
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        shutil.copytree(self.origin, self.workspace, ignore=IGNORE)
        self.baseline_hash = tree_hash(self.workspace)
        self.file_hashes = {
            str(p.relative_to(self.workspace)): file_hash(p)
            for p in self.workspace.rglob("*")
            if p.is_file() and _keep(p, self.workspace)
        }
        self.state = CandidateState.SNAPSHOTTED
        return self

    def origin_matches_baseline(self) -> bool:
        return tree_hash(self.origin) == self.origin_hash

    def changed_files(self) -> list[str]:
        if not self.workspace.exists():
            return []
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
        self.state = CandidateState.DISCARDED

    def accept_isolated(self) -> None:
        """Mark verified. Does not copy back onto origin."""
        self.accepted = True
        if self.state not in {CandidateState.WAITING_FOR_APPROVAL, CandidateState.READY_FOR_PROMOTION}:
            self.state = CandidateState.VERIFIED
