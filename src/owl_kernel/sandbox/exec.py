from __future__ import annotations

import ast
import os
import subprocess
import tempfile
from pathlib import Path

FORBIDDEN = ("os.system", "subprocess", "socket", "shutil.rmtree", "eval(", "exec(", "__import__")


class SandboxError(PermissionError):
    pass


class Sandbox:
    def __init__(self, root: str | Path, *, allow: set[str] | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.allow = allow or {"READ", "WRITE", "EXECUTE"}

    def resolve(self, rel: str, *, perm: str = "READ") -> Path:
        if perm not in self.allow:
            raise SandboxError(f"permission {perm} not granted")
        if perm == "SECRETS":
            raise SandboxError("SECRETS never granted")
        if perm == "NETWORK":
            raise SandboxError("NETWORK not granted by default")
        raw = Path(rel)
        p = (self.root / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if self.root not in p.parents and p != self.root:
            raise SandboxError("path traversal blocked")
        if any(part.startswith(".") and part not in {".", ".."} for part in p.relative_to(self.root).parts):
            raise SandboxError("hidden paths blocked")
        return p

    def read(self, rel: str) -> str:
        p = self.resolve(rel, perm="READ")
        return p.read_text(encoding="utf-8", errors="replace")[:80_000]

    def write(self, rel: str, content: str) -> None:
        p = self.resolve(rel, perm="WRITE")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def run_python(self, source: str, *, timeout: int = 8) -> str:
        if "EXECUTE" not in self.allow:
            raise SandboxError("EXECUTE not granted")
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise SandboxError(f"syntax: {e}") from e
        dumped = ast.dump(tree)
        if any(f in source or f in dumped for f in ("os.system", "subprocess", "socket")):
            raise SandboxError("unsafe python")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=self.root) as f:
            f.write(source)
            name = f.name
        try:
            proc = subprocess.run(
                ["python3", name],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={"PYTHONPATH": "", "PATH": os.environ.get("PATH", "")},
            )
            out = (proc.stdout + proc.stderr)[:4000]
            if proc.returncode != 0:
                raise SandboxError(out or f"exit {proc.returncode}")
            return out
        finally:
            Path(name).unlink(missing_ok=True)

    def run_pytest(self, *, timeout: int = 30) -> tuple[bool, str]:
        if "EXECUTE" not in self.allow:
            raise SandboxError("EXECUTE not granted")
        proc = subprocess.run(
            ["python3", "-m", "pytest", "-q"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(self.root)},
        )
        out = (proc.stdout + proc.stderr)[:8000]
        return proc.returncode == 0, out
