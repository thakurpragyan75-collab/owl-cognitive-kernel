from __future__ import annotations

from pathlib import Path
from typing import Any

from ..codegraph.index import index_repo
from ..git_safety import snapshot
from ..patch.engine import apply_patch, make_replace
from ..sandbox.exec import Sandbox
from .spec import ToolError, ToolSpec


def build_tools(root: Path, sandbox: Sandbox) -> dict[str, ToolSpec]:
    def inspect_repository(**_: Any) -> dict:
        g = index_repo(root)
        return {"files": list(g.files.keys())[:80], "symbols": len(g.symbols), "tests": g.tests}

    def list_files(path: str = ".", **_: Any) -> dict:
        p = sandbox.resolve(path, perm="READ")
        names = [c.name + ("/" if c.is_dir() else "") for c in sorted(p.iterdir())[:80]]
        return {"entries": names}

    def search_code(query: str, **_: Any) -> dict:
        if not query:
            raise ToolError("query required")
        q = query.lower()
        hits = []
        for p in root.rglob("*"):
            if p.suffix not in {".py", ".ts", ".tsx", ".js", ".md"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if q in text.lower() or q in p.name.lower():
                rel = str(p.relative_to(root))
                hits.append(rel)
            if len(hits) >= 30:
                break
        return {"hits": hits}

    def read_file(path: str, **_: Any) -> dict:
        if not path:
            raise ToolError("path required")
        body = sandbox.read(path)
        return {"path": path, "body": body}

    def search_symbols(query: str, **_: Any) -> dict:
        g = index_repo(root)
        q = (query or "").lower()
        hits = [s.__dict__ for s in g.symbols if q in s.name.lower()]
        return {"symbols": hits[:40]}

    def read_symbol(name: str, **_: Any) -> dict:
        g = index_repo(root)
        for s in g.symbols:
            if s.name == name:
                body = sandbox.read(s.path)
                return {"symbol": s.__dict__, "body": body}
        return {"symbol": None}

    def inspect_dependencies(**_: Any) -> dict:
        g = index_repo(root)
        return {"imports": g.imports}

    def inspect_tests(**_: Any) -> dict:
        g = index_repo(root)
        return {"tests": g.tests}

    def apply_patch_tool(file: str, new_content: str, reason: str = "", **_: Any) -> dict:
        if not file or new_content is None:
            raise ToolError("file and new_content required")
        patch = make_replace(root, file, new_content, reason or "model patch")
        apply_patch(root, patch)
        return {"applied": file, "reason": reason}

    def run_tests(**_: Any) -> dict:
        ok, out = sandbox.run_pytest()
        return {"passed": ok, "output": out}

    def run_python(source: str, **_: Any) -> dict:
        if not source:
            raise ToolError("source required")
        out = sandbox.run_python(source)
        return {"output": out}

    def git_status(**_: Any) -> dict:
        return snapshot(root)

    def git_diff(**_: Any) -> dict:
        snap = snapshot(root)
        return {"git": snap.get("git"), "status": snap.get("status", "")}

    tools = [
        ToolSpec("inspect_repository", "1", frozenset({"READ"}), "none", True, 15, (), inspect_repository),
        ToolSpec("list_files", "1", frozenset({"READ"}), "none", True, 10, (), list_files),
        ToolSpec("search_code", "1", frozenset({"READ"}), "none", True, 20, ("query",), search_code),
        ToolSpec("read_file", "1", frozenset({"READ"}), "none", True, 10, ("path",), read_file),
        ToolSpec("search_symbols", "1", frozenset({"READ"}), "none", True, 15, (), search_symbols),
        ToolSpec("read_symbol", "1", frozenset({"READ"}), "none", True, 10, ("name",), read_symbol),
        ToolSpec("inspect_dependencies", "1", frozenset({"READ"}), "none", True, 15, (), inspect_dependencies),
        ToolSpec("inspect_tests", "1", frozenset({"READ"}), "none", True, 10, (), inspect_tests),
        ToolSpec("apply_patch", "1", frozenset({"WRITE"}), "writes files", True, 10, ("file", "new_content"), apply_patch_tool),
        ToolSpec("run_tests", "1", frozenset({"EXECUTE"}), "runs tests", False, 60, (), run_tests),
        ToolSpec("run_python", "1", frozenset({"EXECUTE"}), "runs python", False, 8, ("source",), run_python),
        ToolSpec("git_status", "1", frozenset({"GIT", "READ"}), "none", True, 10, (), git_status),
        ToolSpec("git_diff", "1", frozenset({"GIT", "READ"}), "none", True, 10, (), git_diff),
        ToolSpec("finish", "1", frozenset(), "none", True, 1, (), lambda **k: {"done": True, **k}),
    ]
    return {t.name: t for t in tools}
