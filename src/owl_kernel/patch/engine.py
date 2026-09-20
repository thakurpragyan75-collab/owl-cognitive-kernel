from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Patch:
    target: str
    expected_hash: str
    content: str
    reason: str
    risk: str = "low"
    tests_affected: tuple[str, ...] = ()


class PatchError(ValueError):
    pass


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def apply_patch(root: Path, patch: Patch) -> None:
    path = (root / patch.target).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise PatchError("patch outside workspace")
    if path.exists():
        current = sha(path.read_text(encoding="utf-8"))
        if current != patch.expected_hash:
            raise PatchError("base state mismatch — file changed under us")
    elif patch.expected_hash:
        raise PatchError("expected existing file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(patch.content, encoding="utf-8")


def make_replace(root: Path, rel: str, content: str, reason: str) -> Patch:
    path = root / rel
    expected = sha(path.read_text(encoding="utf-8")) if path.exists() else ""
    return Patch(target=rel, expected_hash=expected, content=content, reason=reason)
