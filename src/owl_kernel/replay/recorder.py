from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class Recorder:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, trace_id: str, kind: str, payload: dict[str, Any]) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "kind": kind,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def replay(self, trace_id: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if trace_id is None or row.get("trace_id") == trace_id:
                out.append(row)
        return out

    def dry_run(self, trace_id: str) -> Iterator[str]:
        for row in self.replay(trace_id):
            yield f"{row['ts']} {row['kind']} {json.dumps(row['payload'])[:200]}"
