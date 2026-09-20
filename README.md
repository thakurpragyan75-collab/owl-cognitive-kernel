# OWL Cognitive Kernel

Standalone intent compiler + execution kernel for [OWL](https://github.com/thakurpragyan75-collab/owl).

OWL never grants the coding agent implicit access to the machine. The kernel is the authority. The model only proposes JSON tool actions.

```
USER → OWL → explicit repository.path → kernel.v1
     → Intent IR → DAG → isolated candidate
     → model ↔ tools → tests → verify
     → WAITING_FOR_APPROVAL → human approve → READY_FOR_PROMOTION
```

The origin repository is **never** written. `READY_FOR_PROMOTION` does not copy files back.

## Local start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m owl_kernel.service --host 127.0.0.1 --port 8770
python -m owl_kernel.cli --repo /absolute/path/to/your/project \
  "Inspect this repository, find failing tests, repair them, verify the candidate."
```

`--repo` is required. HTTP `start_task` requires `repository.path`. There is **no** silent `examples/shop_repo` default.

Allowed roots: `/tmp`, `/workspace`, `$OWL_KERNEL_ALLOWED_ROOTS`, the kernel checkout (CLI examples only). Paths under `/etc`, `/proc`, `/sys`, `/dev`, `/root` are rejected. Symlinks that resolve outside an allowed root are rejected.

## kernel.v1 (loopback only)

Base: `http://127.0.0.1:8770`

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/health` | `{ok, protocol, service: owl-kernel, version, jobs}` |
| POST | `/v1/compile_intent` | `{request_id, source}` |
| POST | `/v1/start_task` | **requires** `repository.path` |
| GET | `/v1/tasks` | list |
| GET | `/v1/tasks/{id}` | snapshot |
| GET | `/v1/tasks/{id}/result` | full result |
| GET | `/v1/tasks/{id}/trace` | events |
| GET | `/v1/tasks/{id}/events` | SSE live stream |
| POST | `/v1/tasks/{id}/cancel` | sets cancel token on the Runtime |
| POST | `/v1/tasks/{id}/approve` | `approval.actor` must be `"human"` |
| POST | `/v1/tasks/{id}/reject` | discard candidate |
| POST | `/v1/tasks/{id}/prepare_promotion` | stale-origin check; does not write origin |

`start_task` example:

```json
{
  "request_id": "req-456",
  "repository": { "path": "/Users/me/projects/owl" },
  "source": "Inspect this repository and repair the failing tests."
}
```

`GET /v1/tasks/{id}/result` includes a `task` object with `changed_files`, `tests: {passed, summary}`, `security`, `candidate`, and `diff`. Origin is never written.

Missing `repository.path` → HTTP 400 `INVALID_REPOSITORY`. The kernel will not substitute a demo repo.

## Candidate states

`ORIGIN_DISCOVERED → BASELINED → SNAPSHOTTED → RUNNING → VERIFYING → VERIFIED → WAITING_FOR_APPROVAL → READY_FOR_PROMOTION`

or `FAILED` / `CANCELLED` / `DISCARDED` / `PROMOTION_REJECTED`.

A model string `"approved"` is not approval. `actor` must be `"human"`.

If the origin tree hash changed after snapshot, promotion is rejected. User work is not overwritten.

## Default coding provider

`mock-coder` is a **deterministic local synthesizer** of single-return Python functions from assert oracles. It is **not** an LLM. Qwen3-Coder / Devstral / cloud are optional OpenAI-compatible URLs and are used only when their health check succeeds.

## Security (enforced in code)

- MODEL ≠ AUTHORITY
- file comments ≠ instructions
- repository path ≠ extra permissions
- text `"approve"` ≠ human approval
- NETWORK denied by default
- SECRETS never granted
- origin not modified before a future explicit promotion operation (not implemented)

Sandbox is **application-level** (path confinement + AST scan). Not an OS jail.

Traces list events. They do **not** re-execute tools.

## OWL

Say `kernel inspect this repo and fix failing tests`. OWL reads the trusted repo path from `OWL_KERNEL_REPO` (server-side) and sends it as `repository.path`. Say `approve` or `reject` afterward. If the kernel is down, chat still works.

## Demo fixture

`examples/shop_repo` is only for local CLI experiments when you pass that path explicitly.
