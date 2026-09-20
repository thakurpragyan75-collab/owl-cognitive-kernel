from owl_kernel.models.router import ModelRouter


def test_default_is_stub_when_giants_unconfigured():
    r = ModelRouter()
    p = r.choose("coding")
    assert p.info.id == "stub"
    assert p.info.available


def test_does_not_claim_qwen_loaded():
    r = ModelRouter(qwen_url="http://127.0.0.1:9")
    infos = r.available()
    q = next(i for i in infos if i.id == "qwen3-coder")
    assert q.available is False
    assert r.choose("coding").info.id == "stub"


def test_health_lists_stub():
    h = ModelRouter().health_all()
    assert any(x["id"] == "stub" and x["available"] for x in h)
