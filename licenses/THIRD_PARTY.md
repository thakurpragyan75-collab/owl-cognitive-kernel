# Third-party

This repository does **not** vendor Qwen Code, Devstral weights, or other
model repositories.

We reuse *ideas* (tool-calling coding agents, isolated apply-then-test,
permissioned tools) and talk to models through an OpenAI-compatible HTTP
surface if you run them yourself.

| Component | License | Use |
|---|---|---|
| Qwen/Qwen3-Coder-30B-A3B-Instruct | Apache-2.0 | Optional provider ID only |
| mistralai/Devstral-Small-2507 | Apache-2.0 | Optional provider ID only |
| Python | PSF | Runtime |
| pytest | MIT | Tests |

No model weights are included.
