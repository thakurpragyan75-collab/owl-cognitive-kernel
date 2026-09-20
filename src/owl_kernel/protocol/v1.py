"""Stable OWL ↔ kernel protocol. Versioned so OWL HUD can stay unchanged."""

PROTOCOL_VERSION = "kernel.v1"
SERVICE_NAME = "owl-kernel"
SERVICE_VERSION = "0.3.0"

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
    "reject_action",
    "prepare_promotion",
    "context",
)
