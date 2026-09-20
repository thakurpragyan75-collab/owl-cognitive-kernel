"""Cooperative cancellation. Model output cannot clear this flag."""

from __future__ import annotations

import threading


class Cancelled(RuntimeError):
    pass


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()
        self.reason = ""

    def cancel(self, reason: str = "user") -> None:
        self.reason = reason
        self._ev.set()

    def cancelled(self) -> bool:
        return self._ev.is_set()

    def raise_if_cancelled(self) -> None:
        if self._ev.is_set():
            raise Cancelled(self.reason or "cancelled")
