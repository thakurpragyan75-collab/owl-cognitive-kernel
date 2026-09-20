import time
from owl_kernel.ir.schema import Action, Intent
from owl_kernel.kernel.engine import Kernel
from owl_kernel.kernel.states import TaskState
from owl_kernel.kernel.task import Task


def test_independent_reads_run_concurrently(tmp_path):
    k = Kernel(tmp_path / "k.db", max_workers=3)
    intent = Intent(
        goal="parallel",
        actions=[
            Action("a", "inspect_repo", "A", (), "researcher", "READ", "fast_response"),
            Action("b", "search_code", "B", (), "researcher", "READ", "fast_response"),
            Action("c", "analyze_deps", "C", (), "researcher", "READ", "fast_response"),
        ],
        actors=["researcher"],
        permissions=["READ"],
    )
    intent.validate()
    k.submit_intent(intent)
    started = time.perf_counter()

    def handler(t):
        time.sleep(0.25)
        return {"ok": True}

    k.run_to_idle(handler)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.6, elapsed
    assert all(t.state == TaskState.COMPLETED for t in k.all_tasks())
    k.close()


def test_cancel_stops_blocked(tmp_path):
    k = Kernel(tmp_path / "k.db")
    intent = Intent(
        goal="c",
        actions=[
            Action("a", "inspect_repo", "A", (), "researcher", "READ"),
            Action("b", "run_tests", "B", ("a",), "tester", "EXECUTE"),
        ],
        actors=["researcher"],
        permissions=["READ", "EXECUTE"],
    )
    intent.validate()
    tasks = k.submit_intent(intent)
    k.cancel(tasks[0].id)
    assert k.get(tasks[0].id).state == TaskState.CANCELLED
    k.run_to_idle(lambda t: {"ok": True})
    k.close()


def test_retry_reenters_ready(tmp_path):
    k = Kernel(tmp_path / "k.db", max_retries=2)
    t = Task(goal="x", kind="inspect_repo")
    t.transit(TaskState.PLANNED)
    t.transit(TaskState.READY)
    t.transit(TaskState.RUNNING)
    t.transit(TaskState.FAILED)
    assert k.requeue(t, "flaky")
    assert t.state == TaskState.READY
    assert t.retry_count == 1
    k.close()


def test_destructive_not_autoretried(tmp_path):
    k = Kernel(tmp_path / "k.db")
    t = Task(goal="x", kind="apply_patch")
    t.transit(TaskState.PLANNED)
    t.transit(TaskState.READY)
    t.transit(TaskState.RUNNING)
    t.transit(TaskState.FAILED)
    assert k.requeue(t, "nope") is False
    k.close()
