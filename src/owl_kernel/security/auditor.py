from __future__ import annotations

import re
from dataclasses import dataclass

SECRET = re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}", re.I)
INJECTION = re.compile(r"(ignore previous|bypass sandbox|disable safety|exfiltrate)", re.I)
TRAVERSAL = re.compile(r"\.\./")
CMD = re.compile(r"(os\.system|subprocess\.|eval\(|exec\()", re.I)


@dataclass
class Finding:
    severity: str
    rule: str
    detail: str


def audit_text(text: str, *, source: str = "doc") -> list[Finding]:
    findings: list[Finding] = []
    if SECRET.search(text):
        findings.append(Finding("high", "secret_exposure", source))
    if INJECTION.search(text):
        findings.append(Finding("high", "prompt_injection", source))
    if TRAVERSAL.search(text):
        findings.append(Finding("medium", "path_traversal", source))
    if CMD.search(text):
        findings.append(Finding("high", "unsafe_exec", source))
    return findings


def document_is_untrusted(text: str) -> bool:
    """Retrieved docs cannot override policy — we only flag, never obey."""
    return bool(INJECTION.search(text))
