import json
import shutil
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from owl_kernel.repo_target import RepoError, resolve_repository
from owl_kernel.runtime import Runtime
from owl_kernel.service import serve


def _http(method, url, body=None, timeout=8):
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _mini_repo(root: Path, name: str = "util.py"):
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text("def mix(x, y):\n    return x - y\n")
    test = "test_" + name
    mod = name[:-3]
    (root / test).write_text(f"from {mod} import mix\ndef test_mix():\n    assert mix(2, 3) == 5\n")
    return root


def test_repo_required():
    with pytest.raises(RepoError):
        resolve_repository("")
    with pytest.raises(RepoError):
        resolve_repository(None)


def test_repo_traversal_rejected(tmp_path):
    with pytest.raises(RepoError):
        resolve_repository(tmp_path / ".." / "etc", allowed_roots=[tmp_path])


def test_repo_blocked_system():
    with pytest.raises(RepoError):
        resolve_repository("/etc", allowed_roots=[Path("/")])


def test_home_wide_rejected():
    with pytest.raises(RepoError):
        resolve_repository(Path.home(), allowed_roots=[Path("/")])


def test_repo_outside_roots(tmp_path):
    other = tmp_path / "nope"
    other.mkdir()
    allowed = tmp_path / "ok"
    allowed.mkdir()
    with pytest.raises(RepoError):
        resolve_repository(other, allowed_roots=[allowed])


def test_symlink_escape_rejected(tmp_path):
    allowed = tmp_path / "allow"
    allowed.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "x.py").write_text("x=1\n")
    link = allowed / "escape"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink not permitted")
    with pytest.raises(RepoError):
        resolve_repository(link, allowed_roots=[allowed])


def test_explicit_repo_used(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "m.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "test_m.py").write_text("from m import add\ndef test_add():\n    assert add(2,3)==5\n")
    rt = Runtime(tmp_path / "work", repo, allowed_roots=[tmp_path])
    result = rt.execute("Find the bug, fix it, run tests, only apply if tests pass.")
    assert result["ok"] is True
    assert result["repository"]["path"] == str(repo.resolve())
    assert "return a - b" in (repo / "m.py").read_text()


def test_cancel_before_and_during(tmp_path):
    repo = tmp_path / "p"
    repo.mkdir()
    (repo / "a.py").write_text("def n():\n    return 1\n")
    (repo / "test_a.py").write_text("from a import n\ndef test_n():\n    assert n()==1\n")
    rt = Runtime(tmp_path / "w", repo, allowed_roots=[tmp_path])
    rt.request_cancel("test")
    result = rt.execute("Inspect this repository and run tests.")
    assert result["state"] == "CANCELLED"
    assert result["ok"] is False


def test_cancel_race_does_not_report_success(tmp_path):
    repo = tmp_path / "race"
    repo.mkdir()
    (repo / "a.py").write_text("def n():\n    return 1\n")
    (repo / "test_a.py").write_text(
        "from a import n\nimport time\ndef test_n():\n    time.sleep(2)\n    assert n()==1\n"
    )
    rt = Runtime(tmp_path / "w", repo, allowed_roots=[tmp_path])
    box = {}

    def run():
        box["result"] = rt.execute("Inspect this repository and run tests.")

    th = threading.Thread(target=run)
    th.start()
    time.sleep(0.15)
    rt.request_cancel("race")
    th.join(timeout=8)
    result = box.get("result") or {"state": rt.state, "ok": True}
    assert result["state"] == "CANCELLED"
    assert result.get("ok") is False
    assert rt.state != "VERIFIED"
    assert rt.state != "WAITING_FOR_APPROVAL"


def test_http_missing_repo_rejected(tmp_path):
    httpd = serve("127.0.0.1", 0, [tmp_path])
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        code, body = _http("POST", f"http://127.0.0.1:{port}/v1/start_task", {"source": "fix it"})
        assert code == 400
        assert body["error"]["code"] == "INVALID_REPOSITORY"
        assert "shop_repo" not in json.dumps(body)
    finally:
        httpd.shutdown()


def test_http_task_lookup_list_and_unknown(tmp_path):
    repo = _mini_repo(tmp_path / "listed")
    httpd = serve("127.0.0.1", 0, [tmp_path])
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        code, started = _http(
            "POST",
            base + "/v1/start_task",
            {"request_id": "list-1", "repository": {"path": str(repo)}, "source": "Inspect this repository and run tests."},
        )
        assert code == 200
        tid = started["task_id"]
        code, listed = _http("GET", base + "/v1/tasks")
        assert code == 200
        assert any(t["id"] == tid for t in listed["tasks"])
        code, one = _http("GET", f"{base}/v1/tasks/{tid}")
        assert code == 200
        assert one["task"]["id"] == tid
        assert "repository" in one["task"]
        code, missing = _http("GET", f"{base}/v1/tasks/does-not-exist")
        assert code == 404
        assert missing["error"]["code"] == "TASK_NOT_FOUND"
    finally:
        httpd.shutdown()


def test_http_cancel_reaches_runtime(tmp_path):
    repo = tmp_path / "slow"
    repo.mkdir()
    (repo / "a.py").write_text("def n():\n    return 1\n")
    (repo / "test_a.py").write_text(
        "from a import n\nimport time\ndef test_n():\n    time.sleep(6)\n    assert n()==1\n"
    )
    httpd = serve("127.0.0.1", 0, [tmp_path])
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        _, started = _http(
            "POST",
            base + "/v1/start_task",
            {"repository": {"path": str(repo)}, "source": "Inspect this repository and run tests."},
        )
        tid = started["task_id"]
        code, cancelled = _http(
            "POST",
            f"{base}/v1/tasks/{tid}/cancel",
            {"request_id": "req-cancel-1", "reason": "User requested stop"},
        )
        assert code == 200
        assert cancelled["state"] == "CANCEL_REQUESTED"
        state = "RUNNING"
        for _ in range(40):
            time.sleep(0.2)
            _, task = _http("GET", f"{base}/v1/tasks/{tid}")
            state = task.get("task", {}).get("state")
            if state in {"CANCELLED", "FAILED"}:
                break
        assert state == "CANCELLED"
        _, result = _http("GET", f"{base}/v1/tasks/{tid}/result")
        assert result["task"]["state"] == "CANCELLED"
        assert result["ok"] is False
    finally:
        httpd.shutdown()


def test_http_e2e_temp_repo_approval(tmp_path):
    repo = tmp_path / "owl-e2e-project"
    repo.mkdir()
    (repo / "util.py").write_text("def mix(x, y):\n    return x - y\n")
    (repo / "test_util.py").write_text("from util import mix\ndef test_mix():\n    assert mix(2, 3) == 5\n")
    original = (repo / "util.py").read_text()
    httpd = serve("127.0.0.1", 0, [tmp_path])
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    try:
        code, health = _http("GET", base + "/v1/health")
        assert code == 200 and health["ok"] is True and health["version"] == "0.3.0"
        assert health["service"] == "owl-kernel"
        code, started = _http(
            "POST",
            base + "/v1/start_task",
            {
                "request_id": "e2e-1",
                "repository": {"path": str(repo)},
                "source": "Inspect this repository, find the failing tests, repair the defect, verify the candidate, and wait for approval.",
            },
        )
        assert code == 200, started
        assert started["ok"] is True
        assert started["repository"]["path"] == str(repo.resolve())
        tid = started["task_id"]
        state = "RUNNING"
        for _ in range(40):
            time.sleep(0.25)
            _, task = _http("GET", f"{base}/v1/tasks/{tid}")
            state = task.get("task", {}).get("state") or task.get("state")
            if state in {"WAITING_FOR_APPROVAL", "FAILED", "CANCELLED"}:
                break
        assert state == "WAITING_FOR_APPROVAL", task
        _, result = _http("GET", f"{base}/v1/tasks/{tid}/result")
        assert result["candidate"]["original_modified"] is False
        assert result["task"]["tests"]["passed"] is True
        assert "util.py" in result["task"]["changed_files"]
        assert (repo / "util.py").read_text() == original
        code, approved = _http(
            "POST",
            f"{base}/v1/tasks/{tid}/approve",
            {"request_id": "e2e-approve", "approval": {"actor": "human"}},
        )
        assert approved.get("state") == "READY_FOR_PROMOTION"
        assert (repo / "util.py").read_text() == original
        _, trace = _http("GET", f"{base}/v1/tasks/{tid}/trace")
        types = [e.get("type") for e in trace.get("events") or []]
        assert "task.started" in types
        assert "tests.finished" in types
        # model "approved" is not approval
        code, bad = _http(
            "POST",
            f"{base}/v1/tasks/{tid}/approve",
            {"approval": {"actor": "model"}},
        )
        assert bad.get("ok") is False
    finally:
        httpd.shutdown()


def test_http_e2e_exact_tmp_path():
    repo = Path("/tmp/owl-e2e-project")
    if repo.exists():
        shutil.rmtree(repo)
    _mini_repo(repo)
    original = (repo / "util.py").read_text()
    httpd = serve("127.0.0.1", 0, [Path("/tmp")])
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        code, started = _http(
            "POST",
            base + "/v1/start_task",
            {
                "request_id": "e2e-1",
                "repository": {"path": "/tmp/owl-e2e-project"},
                "source": "Inspect this repository, find the failing tests, repair the defect, verify the candidate, and wait for approval.",
            },
        )
        assert code == 200, started
        assert started["repository"]["path"] == str(repo.resolve())
        assert "shop_repo" not in json.dumps(started)
        tid = started["task_id"]
        state = "RUNNING"
        for _ in range(50):
            time.sleep(0.25)
            _, task = _http("GET", f"{base}/v1/tasks/{tid}")
            state = task.get("task", {}).get("state")
            if state in {"WAITING_FOR_APPROVAL", "FAILED", "CANCELLED"}:
                break
        assert state == "WAITING_FOR_APPROVAL", task
        _, result = _http("GET", f"{base}/v1/tasks/{tid}/result")
        assert result["task"]["repository"] == str(repo.resolve())
        assert result["candidate"]["original_modified"] is False
        assert (repo / "util.py").read_text() == original
        _, approved = _http(
            "POST",
            f"{base}/v1/tasks/{tid}/approve",
            {"request_id": "req-approve-1", "approval": {"actor": "human"}},
        )
        assert approved["state"] == "READY_FOR_PROMOTION"
        assert (repo / "util.py").read_text() == original
        cand = Path(result["candidate"]["workspace"])
        assert cand.exists()
        assert "return x + y" in (cand / "util.py").read_text() or "return x+y" in (cand / "util.py").read_text().replace(" ", "")
    finally:
        httpd.shutdown()


def test_owl_api_payload_shape(tmp_path):
    repo = _mini_repo(tmp_path / "owl-payload")
    httpd = serve("127.0.0.1", 0, [tmp_path])
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        code, started = _http(
            "POST",
            base + "/v1/start_task",
            {
                "op": "start_task",
                "request_id": "owl-1",
                "repository": {"path": str(repo)},
                "source": "Inspect this repository and repair the failing tests.",
            },
        )
        assert code == 200
        assert started["ok"] is True
        assert started["repository"]["path"] == str(repo.resolve())
    finally:
        httpd.shutdown()


def test_stale_origin_blocks_promotion(tmp_path):
    repo = tmp_path / "stale"
    repo.mkdir()
    (repo / "u.py").write_text("def mix(x, y):\n    return x - y\n")
    (repo / "test_u.py").write_text("from u import mix\ndef test_mix():\n    assert mix(2,3)==5\n")
    rt = Runtime(tmp_path / "w", repo, wait_for_approval=True, allowed_roots=[tmp_path])
    result = rt.execute("Find the bug, fix it, run tests, only apply if tests pass.")
    assert result["state"] == "WAITING_FOR_APPROVAL"
    (repo / "u.py").write_text("def mix(x, y):\n    return x * y\n")
    out = rt.approve("human")
    assert out.get("ok") is False
    assert out.get("state") == "PROMOTION_REJECTED" or out.get("error", {}).get("code") == "STALE_ORIGIN"
    # origin was user-modified; kernel must not overwrite
    assert "*" in (repo / "u.py").read_text()


def test_reject_discards(tmp_path):
    repo = tmp_path / "rj"
    repo.mkdir()
    (repo / "u.py").write_text("def mix(x, y):\n    return x - y\n")
    (repo / "test_u.py").write_text("from u import mix\ndef test_mix():\n    assert mix(2,3)==5\n")
    rt = Runtime(tmp_path / "w", repo, wait_for_approval=True, allowed_roots=[tmp_path])
    rt.execute("Find the bug, fix it, run tests.")
    out = rt.reject("Do not apply this change")
    assert out["state"] == "DISCARDED"
    assert not (tmp_path / "w" / "isolated").exists()


def test_sse_emits_events(tmp_path):
    repo = tmp_path / "sse"
    repo.mkdir()
    (repo / "u.py").write_text("def mix(x, y):\n    return x - y\n")
    (repo / "test_u.py").write_text("from u import mix\ndef test_mix():\n    assert mix(2,3)==5\n")
    httpd = serve("127.0.0.1", 0, [tmp_path])
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        _, started = _http("POST", base + "/v1/start_task", {"repository": {"path": str(repo)}, "source": "Find the bug, fix it, run tests."})
        tid = started["task_id"]
        for _ in range(40):
            time.sleep(0.2)
            _, task = _http("GET", f"{base}/v1/tasks/{tid}")
            if task.get("task", {}).get("state") in {"WAITING_FOR_APPROVAL", "FAILED"}:
                break
        req = Request(f"{base}/v1/tasks/{tid}/events")
        with urlopen(req, timeout=8) as r:
            chunk = r.read(800).decode()
        assert "event:" in chunk
        assert "task.started" in chunk or "tests.finished" in chunk
    finally:
        httpd.shutdown()


def test_no_runtime_fixture_healer():
    text = Path("src/owl_kernel/runtime.py").read_text()
    assert "def add(" not in text
    assert "in_stock" not in text
