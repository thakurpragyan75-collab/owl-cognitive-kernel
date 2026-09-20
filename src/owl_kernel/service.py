"""Loopback kernel.v1 HTTP service. Bind 127.0.0.1 only.

The service holds Runtime objects. JOBS is not a fake second state machine.
"""

from __future__ import annotations

import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapter_owl import health as adapter_health
from .ir.compiler import CompilerError, compile_intent
from .protocol.v1 import PROTOCOL_VERSION, SERVICE_VERSION
from .repo_target import RepoError, RepoTarget, resolve_repository
from .runtime import Runtime


class TaskRecord:
    def __init__(self, runtime: Runtime, work: str, request_id: str):
        self.runtime = runtime
        self.work = work
        self.request_id = request_id
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()

    @property
    def id(self) -> str:
        return self.runtime.task_id

    def snapshot(self) -> dict:
        rt = self.runtime
        cand = rt.candidate
        return {
            "id": rt.task_id,
            "state": rt.state,
            "repository": str(rt.repo),
            "agent": "debugger",
            "model": rt.metrics.provider or "mock-coder",
            "attempt": rt.attempt,
            "candidate_state": cand.state.value if cand else "NONE",
        }


class Registry:
    def __init__(self, *, allowed_roots: list[Path] | None = None):
        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self.allowed_roots = allowed_roots

    def add(self, rec: TaskRecord) -> None:
        with self._lock:
            self._tasks[rec.id] = rec

    def get(self, tid: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(tid)

    def list(self) -> list[TaskRecord]:
        with self._lock:
            return list(self._tasks.values())

    def jobs(self) -> int:
        with self._lock:
            return len(self._tasks)


REGISTRY = Registry()


def _err(code: str, message: str, request_id: str = "") -> dict:
    body: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if request_id:
        body["request_id"] = request_id
    return body


def _json(handler: BaseHTTPRequestHandler, code: int, body: dict) -> None:
    raw = json.dumps(body).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(raw)


def _read(handler: BaseHTTPRequestHandler) -> dict:
    n = int(handler.headers.get("Content-Length") or 0)
    if n <= 0:
        return {}
    if n > 200_000:
        return {"_parse_error": "payload too large"}
    try:
        return json.loads(handler.rfile.read(n).decode())
    except json.JSONDecodeError:
        return {"_parse_error": "invalid json"}


def _repo_from_body(body: dict) -> RepoTarget:
    repo_obj = body.get("repository")
    path = None
    if isinstance(repo_obj, dict):
        path = repo_obj.get("path")
    elif isinstance(repo_obj, str):
        path = repo_obj
    if not path:
        path = body.get("repo")
    return resolve_repository(path, allowed_roots=REGISTRY.allowed_roots)


def _split_task_path(path: str) -> tuple[str, str]:
    # /v1/tasks/{id}[/action]
    rest = path[len("/v1/tasks/") :]
    parts = [p for p in rest.split("/") if p]
    if not parts:
        return "", ""
    tid = parts[0]
    action = parts[1] if len(parts) > 1 else ""
    return tid, action


class Handler(BaseHTTPRequestHandler):
    server_version = "owl-kernel/0.3"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in {"/v1/health", "/health"}:
            h = adapter_health()
            h["jobs"] = REGISTRY.jobs()
            return _json(self, 200, h)
        if path in {"/v1/tasks", "/v1/list_tasks"}:
            tasks = [
                {"id": r.id, "state": r.runtime.state, "repository": str(r.runtime.repo)}
                for r in REGISTRY.list()
            ]
            return _json(self, 200, {"ok": True, "tasks": tasks})
        if path.startswith("/v1/tasks/"):
            tid, action = _split_task_path(path)
            rec = REGISTRY.get(tid)
            if not rec:
                return _json(self, 404, _err("TASK_NOT_FOUND", f"unknown task {tid}"))
            if action == "trace":
                return _json(
                    self,
                    200,
                    {"ok": True, "task_id": tid, "events": list(rec.runtime.events), "replay": list(rec.runtime.kernel.recorder.dry_run(tid))},
                )
            if action == "result":
                return _json(self, 200, rec.runtime.http_result())
            if action == "events":
                return self._sse(rec)
            snap = rec.snapshot()
            return _json(self, 200, {"ok": True, "task": snap})
        return _json(self, 404, _err("NOT_FOUND", "not_found"))

    def _sse(self, rec: TaskRecord) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        idx = 0
        terminal = {"VERIFIED", "WAITING_FOR_APPROVAL", "READY_FOR_PROMOTION", "FAILED", "CANCELLED", "DISCARDED", "PROMOTION_REJECTED"}
        while True:
            with rec.runtime._cv:
                while idx >= len(rec.runtime.events):
                    if rec.runtime.state in terminal and idx >= len(rec.runtime.events):
                        rec.runtime._cv.wait(timeout=0.2)
                        if rec.runtime.state in terminal and idx >= len(rec.runtime.events):
                            try:
                                self.wfile.write(b"event: stream.end\ndata: {}\n\n")
                                self.wfile.flush()
                            except BrokenPipeError:
                                return
                            return
                    rec.runtime._cv.wait(timeout=0.5)
                    if idx >= len(rec.runtime.events):
                        try:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                        except BrokenPipeError:
                            return
                batch = rec.runtime.events[idx:]
                idx = len(rec.runtime.events)
            for ev in batch:
                line = f"event: {ev['type']}\ndata: {json.dumps(ev.get('data') or {})}\n\n"
                try:
                    self.wfile.write(line.encode())
                    self.wfile.flush()
                except BrokenPipeError:
                    return

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        body = _read(self)
        if body.get("_parse_error"):
            return _json(self, 400, _err("INVALID_JSON", str(body["_parse_error"])))
        req_id = str(body.get("request_id") or uuid4())
        if path == "/v1/compile_intent":
            try:
                ir = compile_intent(str(body.get("source") or ""))
            except (CompilerError, ValueError) as e:
                return _json(self, 400, _err("INVALID_INTENT", str(e), req_id))
            return _json(self, 200, {"ok": True, "request_id": req_id, "intent": ir.to_dict()})
        if path == "/v1/start_task":
            return self._start(body, req_id)
        # REST task actions
        if path.startswith("/v1/tasks/"):
            tid, action = _split_task_path(path)
            rec = REGISTRY.get(tid)
            if not rec:
                # also allow body.task_id
                rec = REGISTRY.get(str(body.get("task_id") or ""))
            if not rec:
                return _json(self, 404, _err("TASK_NOT_FOUND", f"unknown task {tid}", req_id))
            if action == "cancel" or path.endswith("/cancel"):
                rec.runtime.request_cancel(str(body.get("reason") or "User requested stop"))
                return _json(self, 200, {"ok": True, "task_id": rec.id, "state": "CANCEL_REQUESTED", "request_id": req_id})
            if action == "approve":
                approval = body.get("approval") if isinstance(body.get("approval"), dict) else {}
                actor = str(approval.get("actor") or body.get("actor") or "human")
                out = rec.runtime.approve(actor)
                out["request_id"] = req_id
                out["task_id"] = rec.id
                return _json(self, 200 if out.get("ok") else 400, out)
            if action == "reject":
                out = rec.runtime.reject(str(body.get("reason") or ""))
                out["request_id"] = req_id
                return _json(self, 200, out)
            if action == "prepare_promotion":
                out = rec.runtime.prepare_promotion()
                out["request_id"] = req_id
                out["task_id"] = rec.id
                return _json(self, 200 if out.get("ok") else 409, out)
        # legacy aliases
        if path == "/v1/cancel_task":
            rec = REGISTRY.get(str(body.get("task_id") or ""))
            if not rec:
                return _json(self, 404, _err("TASK_NOT_FOUND", "unknown task", req_id))
            rec.runtime.request_cancel(str(body.get("reason") or "user"))
            return _json(self, 200, {"ok": True, "task_id": rec.id, "state": "CANCEL_REQUESTED"})
        if path == "/v1/approve_action":
            rec = REGISTRY.get(str(body.get("task_id") or ""))
            if not rec:
                return _json(self, 404, _err("TASK_NOT_FOUND", "unknown task", req_id))
            out = rec.runtime.approve("human")
            return _json(self, 200 if out.get("ok") else 400, out)
        if path == "/v1/inspect_trace":
            rec = REGISTRY.get(str(body.get("task_id") or ""))
            if not rec:
                return _json(self, 404, _err("TASK_NOT_FOUND", "unknown task", req_id))
            return _json(self, 200, {"ok": True, "task_id": rec.id, "events": rec.runtime.events})
        if path == "/v1/retrieve_result":
            rec = REGISTRY.get(str(body.get("task_id") or ""))
            if not rec:
                return _json(self, 404, _err("TASK_NOT_FOUND", "unknown task", req_id))
            return _json(self, 200, rec.runtime.http_result())
        return _json(self, 404, _err("NOT_FOUND", "not_found", req_id))

    def _start(self, body: dict, req_id: str) -> None:
        source = str(body.get("source") or body.get("goal") or "")
        if not source.strip():
            return _json(self, 400, _err("INVALID_INTENT", "source is required", req_id))
        try:
            target = _repo_from_body(body)
        except RepoError as e:
            return _json(self, 400, _err(e.code, str(e), req_id))
        opts = body.get("options") if isinstance(body.get("options"), dict) else {}
        work = Path(tempfile.mkdtemp(prefix="owl-kernel-"))
        tid = str(uuid4())
        rt = Runtime(
            work,
            target,
            wait_for_approval=True,
            allowed_roots=REGISTRY.allowed_roots,
            max_retries=int(opts.get("max_retries") or 3),
            max_iterations=int(opts.get("max_iterations") or 24),
            timeout_seconds=int(opts.get("timeout_seconds") or 300),
        )
        rt.task_id = tid
        rec = TaskRecord(rt, str(work), req_id)
        REGISTRY.add(rec)
        rt.state = "RUNNING"

        def run() -> None:
            try:
                rt.execute(source)
            except Exception as e:
                rt.state = "FAILED"
                rt.emit("task.completed", {"state": "FAILED", "error": str(e)})

        rec.thread = threading.Thread(target=run, daemon=True)
        rec.thread.start()
        return _json(
            self,
            200,
            {
                "ok": True,
                "protocol": PROTOCOL_VERSION,
                "request_id": req_id,
                "task_id": tid,
                "state": "RUNNING",
                "repository": {"path": str(target.path), "label": target.label, "baseline_hash": target.baseline_hash, "id": target.id},
            },
        )


def serve(host: str = "127.0.0.1", port: int = 8770, allowed_roots: list[Path] | str | None = None) -> ThreadingHTTPServer:
    roots: list[Path] | None
    if isinstance(allowed_roots, str):
        roots = [Path(allowed_roots).resolve()]
    elif allowed_roots is None:
        roots = None
    else:
        roots = allowed_roots
    global REGISTRY
    REGISTRY = Registry(allowed_roots=roots)
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="owl-kernel-service")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--allowed-root", action="append", default=[])
    args = p.parse_args(argv)
    roots = [Path(r).resolve() for r in args.allowed_root] or None
    httpd = serve(args.host, args.port, roots)
    print(json.dumps({"ok": True, "bind": f"{args.host}:{args.port}", "protocol": PROTOCOL_VERSION, "version": SERVICE_VERSION}))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
