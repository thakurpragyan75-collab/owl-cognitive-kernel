# OWL Cognitive Kernel

Standalone **intent compiler + execution kernel** for [OWL](https://github.com/thakurpragyan75-collab/owl).

This is **not** a chatbot and **not** a rewrite of OWL. OWL keeps the HUD, voice, memory, relics, arcade, Studio. This kernel sits underneath, later, via a thin adapter (`kernel.v1`).

```
NATURAL LANGUAGE
    → INTENT IR
    → VALIDATION
    → TASK DAG
    → SANDBOXED AGENTS
    → TESTS
    → SECURITY
    → COMMIT OR ROLLBACK
```

## What it is

An AI *instruction* is treated like source code. The compiler turns it into a structured, serializable **Intent IR**. The kernel schedules a DAG with a real state machine, runs tools in a sandbox, records a flight log, and can replay it.

Large models are **optional providers**. Default brain is a deterministic stub so an 8GB machine still runs the kernel.

## Official models (optional, not in git)

Verified 2026-09, both **Apache-2.0**:

| Provider | Hugging Face id | Size | Machine |
|---|---|---|---|
| Qwen3-Coder | `Qwen/Qwen3-Coder-30B-A3B-Instruct` | ~61GB bf16 / ~20GB 4-bit | not 8GB |
| Devstral Small 2507 | `mistralai/Devstral-Small-2507` | ~94GB bf16 | Mac 32GB / RTX 4090 |

`max_loaded: 1` — never load both. Weights are never committed.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m owl_kernel.cli --repo examples/fixture_repo \
  "Find the bug, fix it, run tests, only apply if tests pass."
```

## Demo (real, not faked)

`examples/fixture_repo` ships with `add()` returning `a - b`. The kernel:

1. Compiles the sentence into IR  
2. Builds a task graph  
3. Copies the repo into an isolated workspace  
4. Indexes symbols/imports/tests  
5. Runs pytest (fails)  
6. Diagnoses, patches with base-hash check  
7. Re-runs tests (pass)  
8. Security-audits  
9. Writes a trace you can replay  

The original fixture is never mutated.

## OWL integration

Do **not** merge this into random OWL files. Use:

```python
from owl_kernel.adapter_owl import health, start_goal
```

Protocol version: `kernel.v1` (`src/owl_kernel/protocol/v1.py`).

## Layout

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
