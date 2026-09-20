from owl_kernel.memory.store import Memory
from owl_kernel.plugins import Plugin, PluginRegistry


def test_memory_does_not_promote_assumptions(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.add("project", "assumption", "maybe the bug is in chat", "agent")
    m.add("project", "fact", "add() subtracts", "test")
    assert m.facts() == ["add() subtracts"]


def test_plugin_cannot_request_secrets():
    r = PluginRegistry()
    try:
        r.register(Plugin("evil", "1", ["x"], ["SECRETS"]))
        assert False
    except ValueError:
        pass
