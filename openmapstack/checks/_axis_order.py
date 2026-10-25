"""Bounded static evidence for DuckDB connection axis-order declarations.

This is deliberately not a Python interpreter. Only straight-line, literal
SQL and the packaged setup helpers can establish a pass. Cross-function
connections, conditional setup and constructed SQL need runtime evidence.
"""
from __future__ import annotations

import ast
import re

_SENSITIVE = re.compile(r"\bST_Transform\s*\(|\bCOPY\b[\s\S]*\bFORMAT\s+['\"]?GDAL\b", re.I)
_SETTING = re.compile(r"^\s*SET\s+geometry_always_xy\s*(?:=|TO)\s*(true|false)\s*$", re.I)


def _sql_statements(sql: str) -> list[str]:
    """Split only outside quoted SQL values/identifiers; reject comments."""
    parts, start, quote, index = [], 0, None, 0
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif sql[index:index + 2] in ('--', '/*'):
            raise ValueError('SQL comments need a full parser')
        elif char == ';':
            parts.append(sql[start:index])
            start = index + 1
        index += 1
    if quote:
        raise ValueError('unterminated SQL quote')
    parts.append(sql[start:])
    return parts


def inspect_python(text: str) -> tuple[list[int], list[int], list[int]]:
    tree = ast.parse(text)
    helpers = {}
    duckdb_names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'openmapstack.checks.spatial':
            helpers.update({a.asname or a.name: a.name for a in node.names})
        if isinstance(node, ast.Import):
            duckdb_names.update(a.asname or a.name for a in node.names if a.name == 'duckdb')
    # Shadowed imports cannot establish which implementation is called.
    rebound = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    rebound.update(n.arg for n in ast.walk(tree) if isinstance(n, ast.arg))
    rebound.update(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)))
    helpers = {name: value for name, value in helpers.items() if name not in rebound}
    duckdb_names -= rebound
    if not duckdb_names and not helpers:
        return [], [], [0]  # The engine cannot be established.
    checked, missing, ambiguous = [], [], []

    def scan(body):
        connections = {}
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scan(statement.body)
                continue
            # A branch/loop/try may skip, replace or reset a connection. Do not
            # use its setting as proof for later statements (or vice versa).
            if not isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign)):
                calls = [n for n in ast.walk(statement) if isinstance(n, ast.Call)]
                if calls:
                    ambiguous.append(statement.lineno)
                    connections = {name: None for name in connections}
                continue
            value = getattr(statement, 'value', None)
            targets = statement.targets if isinstance(statement, ast.Assign) else (
                [statement.target] if isinstance(statement, ast.AnnAssign) else [])
            for target in targets:
                if isinstance(target, ast.Name):
                    state = None
                    if isinstance(value, ast.Call):
                        fn = value.func
                        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in duckdb_names and fn.attr == 'connect':
                            state = False
                        if isinstance(fn, ast.Name) and helpers.get(fn.id) in ('connect_spatial', 'require_spatial'):
                            state = True
                    connections[target.id] = state
            # Only direct calls are admitted: comprehensions, lambdas and
            # short-circuit expressions do not guarantee execution order.
            if not isinstance(value, ast.Call):
                if any(isinstance(n, ast.Call) for n in ast.walk(statement)):
                    ambiguous.append(statement.lineno)
                continue
            fn = value.func
            if isinstance(fn, ast.Name) and helpers.get(fn.id) == 'configure_spatial_axes':
                if value.args and isinstance(value.args[0], ast.Name):
                    connections[value.args[0].id] = True
                else:
                    ambiguous.append(statement.lineno)
                continue
            # Chained fetchone()/fetchall() still execute the inner SQL call.
            call = value
            while isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Call):
                call = call.func.value
            fn = call.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.attr in ('execute', 'sql', 'query')):
                continue
            receiver = fn.value.id
            if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(call.args[0].value, str):
                ambiguous.append(statement.lineno)
                connections[receiver] = None
                continue
            sql = call.args[0].value
            try:
                statements = _sql_statements(sql)
            except ValueError:
                ambiguous.append(statement.lineno)
                connections[receiver] = None
                continue
            for part in statements:
                if _SETTING.fullmatch(part):
                    if receiver in connections and connections[receiver] is not None:
                        connections[receiver] = True  # false is explicit too.
                    else:
                        ambiguous.append(statement.lineno)
                elif 'geometry_always_xy' in part.lower():
                    ambiguous.append(statement.lineno)
                    connections[receiver] = None
                if _SENSITIVE.search(part):
                    state = connections.get(receiver)
                    (checked if state is True else missing if state is False else ambiguous).append(statement.lineno)
    scan(tree.body)
    return checked, missing, ambiguous
