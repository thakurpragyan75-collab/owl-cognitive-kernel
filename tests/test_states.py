from owl_kernel.kernel.states import TaskState, TransitionError, can_transition, require


def test_legal_happy_path():
    s = TaskState.CREATED
    for nxt in (TaskState.PLANNED, TaskState.READY, TaskState.RUNNING, TaskState.VERIFYING, TaskState.COMPLETED):
        require(s, nxt)
        s = nxt


def test_illegal_completed_to_running():
    assert not can_transition(TaskState.COMPLETED, TaskState.RUNNING)
    try:
        require(TaskState.COMPLETED, TaskState.RUNNING)
        assert False
    except TransitionError:
        pass


def test_failed_retry():
    require(TaskState.FAILED, TaskState.RETRYING)
    require(TaskState.RETRYING, TaskState.RUNNING)
