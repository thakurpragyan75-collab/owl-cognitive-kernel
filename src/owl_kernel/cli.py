from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .repo_target import RepoError, resolve_repository
from .runtime import Runtime


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="owl-kernel")
    p.add_argument("source", nargs="?", default="Inspect this repository, find failing tests, repair them, verify the candidate.")
    p.add_argument("--repo", required=True, help="Explicit repository path. Never inferred.")
    p.add_argument("--wait-approval", action="store_true")
    args = p.parse_args(argv)
    try:
        target = resolve_repository(args.repo, workspace_root=Path.cwd())
    except RepoError as e:
        print(json.dumps({"ok": False, "error": {"code": e.code, "message": str(e)}}))
        return 2
    with tempfile.TemporaryDirectory() as td:
        rt = Runtime(td, target, wait_for_approval=args.wait_approval)
        result = rt.execute(args.source)
    slim = {k: v for k, v in result.items() if k not in {"replay", "events"}}
    print(json.dumps(slim, indent=2)[:4000])
    print("replay_events", len(result.get("replay") or []))
    print("state", result.get("state"))
    print("repository", result.get("repository"))
    if result.get("state") == "WAITING_FOR_APPROVAL":
        return 0
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
