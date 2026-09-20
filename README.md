# OWL Cognitive Kernel

Standalone **intent compiler + execution kernel** for [OWL](https://github.com/thakurpragyan75-collab/owl).

This is **not** a chatbot and **not** a rewrite of OWL. OWL keeps the HUD, voice, Nest, relics, arcade, Studio, Gaze, Print. This kernel sits beside OWL via `kernel.v1` on **loopback `127.0.0.1:8770`**.

```
NATURAL LANGUAGE
  → Intent IR
  → DAG (dependency-aware, bounded parallel reads)
  → Isolated candidate workspace
  → Model ↔ tool loop (schema-validated)
  → Tests + security audit
  → Accept isolated candidate OR discard
  → Flight log / replay
```

The original repository is **never** written. Rollback = delete the candidate copy.

## Status of claims (honest)

| Capability | Status |
|---|---|
| Intent IR + validation + cycle detection | **IMPLEMENTED** |
| DAG scheduler, parallel READ tasks, cancel | **IMPLEMENTED** |
| Isolated candidate snapshot / discard | **IMPLEMENTED** |
| Tool protocol with schema + role permissions | **IMPLEMENTED** |
| Model-driven agent loop | **IMPLEMENTED** |
| Default local coding model (`mock-coder`) | **IMPLEMENTED** — test-oracle synthesizer, not a neural net |
| Qwen3-Coder / Devstral / cloud | **OPTIONAL** — OpenAI-compatible URL, health-checked, never faked |
| HTTP `kernel.v1` on 127.0.0.1:8770 | **IMPLEMENTED** |
| Prompt-injection refusal on the user goal | **IMPLEMENTED** |
| Repo comments treated as untrusted content | **IMPLEMENTED** |
| Application sandbox (path + AST + no NETWORK/SECRETS) | **IMPLEMENTED** — **not** an OS/container jail |
| Origin-repo git commit / push | **NOT IMPLEMENTED** (force-push API refuses; isolated only) |
| Deterministic replay of side effects | **PARTIAL** — traces replay; tools are not re-executed |
| Tree-sitter multi-language graph | **NOT IMPLEMENTED** — Python `ast` + file hashes for ts/js/md |
| Universal rollback of arbitrary external ops | **NOT IMPLEMENTED** |
| True multi-agent debate | **PARTIAL** — roles have real permission/tool boundaries |

## Default brain on 8GB

No 30B/24B model is required. Startup uses:

1. `stub` for fast_response
2. `mock-coder` for coding when no giant endpoint is healthy

`mock-coder` reads tests and source through tools, applies a weak first candidate, then synthesizes a single-return function body that satisfies extracted assert oracles. It has **no hardcoded demo answer**.

Giant models (optional, not in git, Apache-2.0):

| id | Hugging Face | When |
|---|---|---|
| Qwen3-Coder | `Qwen/Qwen3-Coder-30B-A3B-Instruct` | OpenAI-compat URL, ~20GB 4-bit — not 8GB |
| Devstral Small 2507 | `mistralai/Devstral-Small-2507` | Mac 32GB / RTX 4090 |

`max_loaded: 1`. Weights are never committed.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m owl_kernel.cli --repo examples/shop_repo \
  "Inspect this repo, find the failing behavior, repair it, test, only keep if tests pass."
python -m owl_kernel.service --port 8770 --repo examples/shop_repo
```

## Demo

`examples/shop_repo` has two independent defects (`in_stock` uses `>` instead of `>=`, `line_total` ignores discount). The kernel must inspect, test, and patch **without** those strings existing in `runtime.py`.

`examples/fixture_repo` (`add` subtracts) remains as a regression for the same general synthesizer.

## OWL

Thin client: `src/lib/owl/kernelClient.ts` talks `kernel.v1`. If the kernel is down, OWL chat still works. Trigger on purpose: **“kernel …”** or **“run kernel …”**.

## Layout

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
