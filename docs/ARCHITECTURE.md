# Architecture

```mermaid
flowchart TD
  OWL[OWL HUD] --> CTX[Trusted repository.path]
  CTX --> HTTP[kernel.v1 127.0.0.1:8770]
  HTTP --> REG[Task registry / Runtime]
  REG --> C[Cancel token]
  REG --> IR[Intent compiler]
  IR --> DAG[DAG scheduler]
  DAG --> SNAP[Isolated candidate]
  SNAP --> LOOP[JSON tool loop]
  LOOP --> T[pytest]
  T --> V[Verify]
  V --> WAIT[WAITING_FOR_APPROVAL]
  WAIT --> HUM[Human approve]
  HUM --> READY[READY_FOR_PROMOTION]
```

Repository targeting is resolved and canonicalized **before** snapshot. The model never supplies the path.

Cancellation is a `CancelToken` on the Runtime, checked in the scheduler, agent loop, and pytest subprocess.

Approval is a Runtime method. `actor` must be `"human"`. Origin is not written.

`mock-coder` is a test-oracle synthesizer, not an LLM.
