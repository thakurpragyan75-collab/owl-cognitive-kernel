from __future__ import annotations

import sqlite3
from pathlib import Path


KINDS = frozenset({"fact", "observation", "assumption", "failed_hypothesis", "strategy"})
LAYERS = frozenset({"working", "task", "project", "long_term", "history"})


class Memory:
    """Facts vs observations. Provenance required. Assumptions never auto-promote."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.execute(
            """CREATE TABLE IF NOT EXISTS mem (
                id INTEGER PRIMARY KEY,
                layer TEXT,
                kind TEXT,
                body TEXT,
                source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.con.commit()

    def add(self, layer: str, kind: str, body: str, source: str) -> None:
        if kind not in KINDS:
            raise ValueError(kind)
        if layer not in LAYERS:
            raise ValueError(layer)
        self.con.execute(
            "INSERT INTO mem(layer, kind, body, source) VALUES (?,?,?,?)",
            (layer, kind, body, source),
        )
        self.con.commit()

    def facts(self, layer: str = "project") -> list[str]:
        cur = self.con.execute("SELECT body FROM mem WHERE layer=? AND kind='fact'", (layer,))
        return [r[0] for r in cur.fetchall()]

    def recent(self, layer: str, kind: str, limit: int = 12) -> list[str]:
        cur = self.con.execute(
            "SELECT body FROM mem WHERE layer=? AND kind=? ORDER BY id DESC LIMIT ?",
            (layer, kind, limit),
        )
        return [r[0] for r in cur.fetchall()]
