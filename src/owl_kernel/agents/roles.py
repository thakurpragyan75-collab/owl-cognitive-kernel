"""Role contracts. Permissions never escalate from a model proposal."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    name: str
    permissions: frozenset[str]
    tools: frozenset[str]
    may_write: bool
    output: str


ROLES: dict[str, Role] = {
    "architect": Role(
        "architect",
        frozenset({"READ"}),
        frozenset({"inspect_repository", "inspect_dependencies", "list_files", "search_symbols"}),
        False,
        "plan",
    ),
    "researcher": Role(
        "researcher",
        frozenset({"READ"}),
        frozenset(
            {
                "inspect_repository",
                "list_files",
                "search_code",
                "read_file",
                "search_symbols",
                "read_symbol",
                "inspect_tests",
            }
        ),
        False,
        "findings",
    ),
    "coder": Role(
        "coder",
        frozenset({"READ", "WRITE"}),
        frozenset({"read_file", "search_code", "list_files", "apply_patch", "search_symbols"}),
        True,
        "patch",
    ),
    "debugger": Role(
        "debugger",
        frozenset({"READ", "WRITE", "EXECUTE"}),
        frozenset(
            {
                "read_file",
                "search_code",
                "apply_patch",
                "run_tests",
                "run_python",
                "inspect_tests",
                "inspect_repository",
                "list_files",
            }
        ),
        True,
        "diagnosis",
    ),
    "tester": Role(
        "tester",
        frozenset({"READ", "EXECUTE"}),
        frozenset({"inspect_tests", "run_tests", "read_file"}),
        False,
        "test_report",
    ),
    "security": Role(
        "security",
        frozenset({"READ"}),
        frozenset({"read_file", "inspect_repository", "list_files"}),
        False,
        "audit",
    ),
    "docs": Role(
        "docs",
        frozenset({"READ"}),
        frozenset({"read_file", "inspect_repository"}),
        False,
        "report",
    ),
}


def role_allows(role: str, tool: str, perm: str) -> bool:
    r = ROLES.get(role)
    if not r:
        return False
    if tool not in r.tools and tool != "finish":
        return False
    if perm not in r.permissions and perm:
        return False
    return True
