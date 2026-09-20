"""Loopback kernel.v1 HTTP service. Bind 127.0.0.1 only."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapter_owl import health as adapter_health
from .ir.compiler import CompilerError, compile_intent
from .protocol.v1 import PROTOCOL_VERSION
from .runtime import Runtime

JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()
DEFAULT_REPO = Path(__file__).resolve().parents[2] / "examples" / "shop_repo"


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
        return {"error": "payload too large"}
    try:
        return json.loads(handler.rfile.read(n).decode())
    except json.JSONDecodeError:
        return {"error": "invalid json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "owl-kernel/1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in {"/v1/health", "/health"}:
            h = adapter_health()
            h["jobs"] = len(JOBS)
            return _json(self, 200, h)
        if path == "/v1/list_tasks":
            with LOCK:
                items = [{"id": k, "ok": v.get("ok"), "state": v.get("state")} for k, v in JOBS.items()]
            return _json(self, 200, {"tasks": items})
        if path.startswith("/v1/tasks/"):
            tid = path.split("/v1/tasks/", 1)[1].split("/")[0]
            with LOCK:
                job = JOBS.get(tid)
            if not job:
                return _json(self, 404, {"error": "unknown_task", "id": tid})
            if path.endswith("/trace"):
                return _json(self, 200, {"id": tid, "replay": job.get("replay") or []})
            if path.endswith("/result"):
                return _json(self, 200, job)
            return _json(self, 200, {"id": tid, "state": job.get("state"), "ok": job.get("ok")})
        return _json(self, 404, {"error": "not_found", "protocol": PROTOCOL_VERSION})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        body = _read(self)
        if body.get("error") and len(body) == 1:
            return _json(self, 400, {"error": body["error"]})
        req_id = str(body.get("request_id") or uuid4())
        if path == "/v1/compile_intent":
            try:
                ir = compile_intent(str(body.get("source") or ""))
            except (CompilerError, ValueError) as e:
                return _json(self, 400, {"error": str(e), "request_id": req_id})
            return _json(self, 200, {"request_id": req_id, "intent": ir.to_dict()})
        if path == "/v1/start_task":
            source = str(body.get("source") or body.get("goal") or "")
            repo = Path(body.get("repo") or DEFAULT_REPO)
            work = Path(body.get("work") or (Path("/tmp") / f"owl-kernel-{uuid4().hex[:8]}"))
            tid = str(uuid4())
            with LOCK:
                JOBS[tid] = {"state": "RUNNING", "ok": None, "request_id": req_id}

            def run() -> None:
                try:
                    rt = Runtime(work, repo)
                    result = rt.execute(source)
                    result["state"] = "COMPLETED" if result.get("ok") else "FAILED"
                    result["request_id"] = req_id
                    with LOCK:
                        JOBS[tid] = result
                except Exception as e:
                    with LOCK:
                        JOBS[tid] = {"state": "FAILED", "ok": False, "error": str(e), "request_id": req_id}

            threading.Thread(target=run, daemon=True).start()
            return _json(self, 200, {"task_id": tid, "request_id": req_id, "protocol": PROTOCOL_VERSION})
        if path == "/v1/cancel_task":
            tid = str(body.get("task_id") or "")
            with LOCK:
                job = JOBS.get(tid)
                if job:
                    job["state"] = "CANCELLED"
            return _json(self, 200, {"ok": True, "task_id": tid})
        if path == "/v1/approve_action":
            tid = str(body.get("task_id") or "")
            with LOCK:
                job = JOBS.get(tid)
                if job:
                    job["approved"] = True
            return _json(self, 200, {"ok": True, "task_id": tid, "note": "isolated candidate never writes origin"})
        if path == "/v1/inspect_trace":
            tid = str(body.get("task_id") or "")
            with LOCK:
                job = JOBS.get(tid) or {}
            return _json(self, 200, {"task_id": tid, "replay": job.get("replay") or []})
        if path == "/v1/retrieve_result":
            tid = str(body.get("task_id") or "")
            with LOCK:
                job = JOBS.get(tid)
            if not job:
                return _json(self, 404, {"error": "unknown_task"})
            return _json(self, 200, job)
        return _json(self, 404, {"error": "not_found"})


def serve(host: str = "127.0.0.1", port: int = 8770, repo: str | None = None) -> ThreadingHTTPServer:
    global DEFAULT_REPO
    if repo:
        DEFAULT_REPO = Path(repo)
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="owl-kernel-service")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--repo", default=str(DEFAULT_REPO))
    args = p.parse_args(argv)
    httpd = serve(args.host, args.port, args.repo)
    print(json.dumps({"ok": True, "bind": f"{args.host}:{args.port}", "protocol": PROTOCOL_VERSION}))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
