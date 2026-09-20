from owl_kernel.ir.compiler import compile_intent
from owl_kernel.kernel.engine import Kernel
from owl_kernel.kernel.states import TaskState


def test_dag_and_recovery(tmp_path):
    k = Kernel(tmp_path / "k.db")
    ir = compile_intent("Inspect the repository and run tests.")
    tasks = k.submit_intent(ir, trace_id="t1")
    assert tasks
    # force a running task then recover
    ready = k.ready()
    t = ready[0]
    t.transit(TaskState.RUNNING)
    k._save(t)
    rec = k.recover()
    assert rec
    assert rec[0].state == TaskState.FAILED
    k.close()


def test_timeout_not_needed_for_stub(tmp_path):
    k = Kernel(tmp_path / "k.db")
    ir = compile_intent("Inspect repo.")
    k.submit_intent(ir)
    ran = k.run_to_idle(lambda t: {"ok": True})
    assert ran
    k.close()
