from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .runtime import Runtime


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="owl-kernel")
    p.add_argument("source", nargs="?", default="Find the bug, fix it, test, apply only if tests pass.")
    p.add_argument("--repo", default="examples/shop_repo")
    args = p.parse_args(argv)
    repo = Path(args.repo)
    if not repo.is_absolute():
        here = Path(__file__).resolve().parents[2]
        repo = here / args.repo
    with tempfile.TemporaryDirectory() as td:
        rt = Runtime(td, repo)
        result = rt.execute(args.source)
    print(json.dumps({k: v for k, v in result.items() if k != "replay"}, indent=2)[:4000])
    print("replay_events", len(result.get("replay") or []))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
