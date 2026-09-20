"""Lightweight code intelligence. Python AST first. Tree-sitter optional later."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


SKIP = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", "models"}


@dataclass
class Symbol:
    name: str
    kind: str
    path: str
    line: int


@dataclass
class CodeGraph:
    root: str
    files: dict[str, str] = field(default_factory=dict)  # rel -> hash
    symbols: list[Symbol] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)
    tests: list[str] = field(default_factory=list)

    def files_depending_on(self, module: str) -> list[str]:
        return [p for p, imps in self.imports.items() if any(module in i for i in imps)]

    def tests_for(self, rel: str) -> list[str]:
        stem = Path(rel).stem
        return [t for t in self.tests if stem in t or Path(t).stem.replace("test_", "") in rel]


def file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def index_repo(root: str | Path) -> CodeGraph:
    root = Path(root).resolve()
    g = CodeGraph(root=str(root))
    for p in root.rglob("*"):
        if any(part in SKIP for part in p.parts):
            continue
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if p.suffix == ".py":
            g.files[rel] = file_hash(p)
            _parse_py(p, rel, g)
            if "test" in rel:
                g.tests.append(rel)
        elif p.suffix in {".ts", ".tsx", ".js", ".md", ".toml"}:
            g.files[rel] = file_hash(p)
    return g


def incremental(g: CodeGraph) -> CodeGraph:
    root = Path(g.root)
    current = {}
    for p in root.rglob("*.py"):
        if any(part in SKIP for part in p.parts):
            continue
        rel = str(p.relative_to(root))
        current[rel] = file_hash(p)
    changed = [rel for rel, h in current.items() if g.files.get(rel) != h]
    removed = [rel for rel in g.files if rel not in current and rel.endswith(".py")]
    g.symbols = [s for s in g.symbols if s.path not in changed and s.path not in removed]
    g.tests = [t for t in g.tests if t not in changed and t not in removed]
    for rel in changed:
        _parse_py(root / rel, rel, g)
        g.files[rel] = current[rel]
        if "test" in rel and rel not in g.tests:
            g.tests.append(rel)
    for rel in removed:
        g.files.pop(rel, None)
        g.imports.pop(rel, None)
    return g


def _parse_py(p: Path, rel: str, g: CodeGraph) -> None:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return
    imps = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            g.symbols.append(Symbol(node.name, "function", rel, node.lineno))
        elif isinstance(node, ast.ClassDef):
            g.symbols.append(Symbol(node.name, "class", rel, node.lineno))
        elif isinstance(node, ast.Import):
            imps.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imps.append(node.module)
    g.imports[rel] = imps


def dump(g: CodeGraph, path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "root": g.root,
                "files": g.files,
                "symbols": [s.__dict__ for s in g.symbols],
                "imports": g.imports,
                "tests": g.tests,
            },
            indent=2,
        )
    )
