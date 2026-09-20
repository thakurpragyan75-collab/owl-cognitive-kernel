import json
import threading
import time
from urllib.request import Request, urlopen

from owl_kernel.service import serve


def test_health_and_compile_and_start(tmp_path):
    httpd = serve("127.0.0.1", 0, str(tmp_path))
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    try:
        with urlopen(base + "/v1/health", timeout=2) as r:
            body = json.loads(r.read().decode())
        assert body["ok"] is True
        assert body["protocol"] == "kernel.v1"
        req = Request(
            base + "/v1/compile_intent",
            data=json.dumps({"source": "Inspect the repository and run tests."}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as r:
            compiled = json.loads(r.read().decode())
        assert compiled["intent"]["goal"]
    finally:
        httpd.shutdown()
