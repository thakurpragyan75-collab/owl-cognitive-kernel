"""Compile natural language into Intent IR without requiring a giant model.

The compiler is deterministic. Optional LLM refinement is a later stage and
must not be required for the kernel to run.
"""

from __future__ import annotations

import re
from .schema import Action, Intent

INJECTION = re.compile(
    r"(ignore (all )?(previous|above) instructions|you are now|bypass (the )?sandbox|"
    r"disable safety|exfiltrate|api[_-]?key\s*=)",
    re.I,
)


class CompilerError(ValueError):
    pass


def compile_intent(source: str) -> Intent:
    text = (source or "").strip()
    if not text:
        raise CompilerError("empty source")
    if INJECTION.search(text):
        raise CompilerError("source looks like a prompt-injection attempt")

    lower = text.lower()
    constraints: list[str] = []
    if "only apply" in lower or "if the tests pass" in lower:
        constraints.append("apply_only_if_tests_pass")
    if "do not merge" in lower:
        constraints.append("no_merge")
    if "isolated" in lower or "sandbox" in lower:
        constraints.append("isolated_workspace")
    constraints.append("no_secrets")
    constraints.append("no_unrestricted_shell")

    permissions = ["READ"]
    if any(w in lower for w in ("fix", "patch", "implement", "edit", "write", "create a fix")):
        permissions.append("WRITE")
    if any(w in lower for w in ("test", "pytest", "run")):
        permissions.append("EXECUTE")
    if "commit" in lower or "git" in lower:
        permissions.append("GIT")

    actions = _plan(lower)
    intent = Intent(
        goal=_goal(text),
        actors=["kernel", "coder", "tester", "security"],
        resources=["repository"],
        actions=actions,
        constraints=constraints,
        permissions=sorted(set(permissions)),
        expected_result="verified_diff_or_rollback",
        verification_rules=["tests_must_pass", "security_audit_clean", "patch_base_matches"],
        rollback_policy="isolated_workspace",
        source=text,
    )
    intent.validate()
    return intent


def _goal(text: str) -> str:
    line = text.strip().split("\n")[0]
    return line[:400]


def _plan(lower: str) -> list[Action]:
    """General verb → DAG. Not hardcoded to one example sentence."""
    want_fix = any(w in lower for w in ("fix", "bug", "repair", "patch", "implement", "refactor"))
    want_test = "test" in lower or want_fix
    want_inspect = True
    actions: list[Action] = []

    if want_inspect:
        actions.append(Action("inspect", "inspect_repo", "Discover repository layout", (), "researcher", "READ", "fast_response"))
        actions.append(Action("locate", "search_code", "Locate relevant implementation", ("inspect",), "researcher", "READ", "fast_response"))
        actions.append(Action("analyze", "analyze_deps", "Analyze symbols and imports", ("locate",), "architect", "READ", "reasoning"))
    if want_fix:
        actions.append(Action("candidate", "propose_patch", "Generate candidate fix in isolation", ("analyze",), "coder", "WRITE", "coding"))
        actions.append(Action("apply_isolated", "apply_patch", "Apply candidate in isolated workspace", ("candidate",), "coder", "WRITE", "coding"))
    if want_test:
        dep = ("apply_isolated",) if want_fix else ("analyze",)
        actions.append(Action("focused_tests", "run_tests", "Run focused tests", dep, "tester", "EXECUTE", "fast_response"))
        actions.append(Action("repair", "self_heal", "Diagnose failure and repair with a hard iteration limit", ("focused_tests",), "debugger", "WRITE", "coding"))
        actions.append(Action("retest", "run_tests", "Re-run tests after repair", ("repair",), "tester", "EXECUTE", "fast_response"))
    actions.append(
        Action(
            "verify",
            "verify",
            "Security + constraint verification",
            tuple(a.id for a in actions[-1:]),
            "security",
            "READ",
            "reasoning",
        )
    )
    actions.append(
        Action(
            "report",
            "report",
            "Emit diff, trace, and explanation; commit only if allowed",
            ("verify",),
            "docs",
            "READ",
            "fast_response",
        )
    )
    return actions
