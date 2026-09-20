"""Stable OWL ↔ kernel protocol. Versioned so OWL HUD can stay unchanged."""

PROTOCOL_VERSION = "kernel.v1"

# OWL adapter should only call these operations:
OPS = (
    "compile_intent",
    "start_task",
    "cancel_task",
    "get_task",
    "list_tasks",
    "stream_events",
    "approve_action",
    "inspect_trace",
    "retrieve_result",
    "health",
)
