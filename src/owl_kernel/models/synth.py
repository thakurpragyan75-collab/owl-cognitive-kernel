"""Local coding model body: synthesize a single-return function from test oracles.

This is the *model*, not the kernel. It has no knowledge of any demo filename.
It only sees function source + assert oracles extracted from files the agent
already read.
"""

from __future__ import annotations

import ast
from typing import Any

BINOPS: list[tuple[type, str]] = [
    (ast.Add, "+"),
    (ast.Sub, "-"),
    (ast.Mult, "*"),
    (ast.FloorDiv, "//"),
    (ast.Div, "/"),
    (ast.Mod, "%"),
]
CMPOPS: list[tuple[type, str]] = [
    (ast.Gt, ">"),
    (ast.GtE, ">="),
    (ast.Lt, "<"),
    (ast.LtE, "<="),
    (ast.Eq, "=="),
    (ast.NotEq, "!="),
]


def extract_oracles(src: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.left, ast.Call):
            call = test.left
            if not isinstance(call.func, ast.Name):
                continue
            args = [_literal(a) for a in call.args]
            if any(a is _MISSING for a in args):
                continue
            expected = _compare_expected(test)
            if expected is _MISSING:
                continue
            out.append({"fn": call.func.id, "args": args, "expected": expected})
    return out


_MISSING = object()


def _literal(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -node.operand.value
    return _MISSING


def _compare_expected(cmp: ast.Compare) -> Any:
    op = cmp.ops[0]
    rhs = cmp.comparators[0]
    val = _literal(rhs)
    if val is _MISSING:
        return _MISSING
    if isinstance(op, (ast.Eq, ast.Is)):
        return val
    if isinstance(op, (ast.NotEq, ast.IsNot)):
        return ("not", val)
    return _MISSING


def _return_expr(fn: ast.FunctionDef) -> ast.AST | None:
    for stmt in fn.body:
        if isinstance(stmt, ast.Expr):
            continue
        if isinstance(stmt, ast.Return):
            return stmt.value
    return None


def repair_source(src: str, oracles: list[dict[str, Any]]) -> str | None:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    changed = False
    for i, node in enumerate(tree.body):
        if not isinstance(node, ast.FunctionDef):
            continue
        fn_oracles = [o for o in oracles if o["fn"] == node.name]
        if not fn_oracles:
            continue
        new_fn = _repair_fn(node, fn_oracles)
        if new_fn is None:
            continue
        try:
            new_tree = ast.parse(new_fn)
            tree.body[i] = new_tree.body[0]
            changed = True
        except SyntaxError:
            continue
    if not changed:
        return None
    return ast.unparse(tree) + "\n"


def _repair_fn(fn: ast.FunctionDef, oracles: list[dict[str, Any]]) -> str | None:
    params = [a.arg for a in fn.args.args]
    original = ast.unparse(fn)
    for cand in _candidates(fn, params):
        if _satisfies(cand, oracles) and cand.strip() != original.strip():
            return cand
    return None


def _candidates(fn: ast.FunctionDef, params: list[str]) -> list[str]:
    header = f"def {fn.name}({', '.join(params)}):"
    expr = _return_expr(fn)
    cands = [ast.unparse(fn)]
    if expr is None:
        return cands
    if isinstance(expr, ast.BinOp) and isinstance(expr.left, ast.Name) and isinstance(expr.right, ast.Name):
        a, b = expr.left.id, expr.right.id
        for _, sym in BINOPS:
            cands.append(f"{header}\n    return {a} {sym} {b}")
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
        left = ast.unparse(expr.left)
        right = ast.unparse(expr.comparators[0])
        for _, sym in CMPOPS:
            cands.append(f"{header}\n    return {left} {sym} {right}")
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        cands.append(f"{header}\n    return {ast.unparse(expr.operand)}")
    if isinstance(expr, ast.Constant) and isinstance(expr.value, bool):
        cands.append(f"{header}\n    return {not expr.value}")
    used = {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}
    leftover = [p for p in params if p not in used]
    base = ast.unparse(expr)
    for u in leftover:
        cands.append(f"{header}\n    return ({base}) * (100 - {u}) // 100")
        cands.append(f"{header}\n    return {base} - {u}")
        cands.append(f"{header}\n    return {base} + {u}")
        cands.append(f"{header}\n    return {base} * {u}")
        cands.append(f"{header}\n    return ({base}) * (100 + {u}) // 100")
    seen: set[str] = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _satisfies(fn_src: str, oracles: list[dict[str, Any]]) -> bool:
    ns: dict[str, Any] = {}
    try:
        exec(fn_src, {"__builtins__": {}}, ns)
    except Exception:
        return False
    fn = next((v for v in ns.values() if callable(v)), None)
    if fn is None:
        return False
    for o in oracles:
        expected = o["expected"]
        try:
            got = fn(*o["args"])
        except Exception:
            return False
        if isinstance(expected, tuple) and expected and expected[0] == "not":
            if got == expected[1]:
                return False
        elif got != expected:
            return False
    return True
