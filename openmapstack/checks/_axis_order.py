"""Detect obvious omissions, without trying to prove Python connection state.

Setup anywhere in the source is only a reason to defer to runtime evidence.
Bindings, execution order, aliases and side effects are deliberately not
interpreted: this advisory check can never certify coordinate order.
"""
from __future__ import annotations

import ast
import re

_SENSITIVE = re.compile(r"\bST_Transform\s*\(|\bCOPY\b[\s\S]*\bFORMAT\s+['\"]?GDAL\b", re.I)
_HELPERS = {'configure_spatial_axes', 'connect_spatial', 'require_spatial'}
_SQL_METHODS = {'execute', 'sql', 'query'}


def inspect_python(text: str) -> list[int]:
    """Return sensitive SQL lines only when there is no setup evidence.

    Evidence is syntactic presence, not proof that a setting executes, remains
    set, or belongs to the connection doing the work. Dynamic SQL also defers:
    it might contain setup that cannot be recognized as a literal here.
    """
    tree = ast.parse(text)
    duckdb_seen = False
    helper_names = set(_HELPERS)
    sql_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            duckdb_seen |= any(alias.name == 'duckdb' for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module == 'duckdb':
                duckdb_seen = True
                sql_names.update(alias.asname or alias.name for alias in node.names
                                 if alias.name in _SQL_METHODS)
            elif node.level == 0 and node.module == 'openmapstack.checks.spatial':
                duckdb_seen = True
                helper_names.update(alias.asname or alias.name for alias in node.names
                                    if alias.name in _HELPERS)
    if not duckdb_seen:
        return []

    sensitive = []
    setup_or_unknown = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
        if name in helper_names:
            setup_or_unknown = True
        if not ((isinstance(fn, ast.Attribute) and name in _SQL_METHODS)
                or (isinstance(fn, ast.Name) and name in sql_names)):
            continue
        sql = node.args[0] if node.args else next(
            (kw.value for kw in node.keywords if kw.arg in ('query', 'sql')), None)
        if not isinstance(sql, ast.Constant) or not isinstance(sql.value, str):
            setup_or_unknown = True
            continue
        # A mention may be a RESET, quoted value, or conditional setup. None
        # proves correctness; all make the omission diagnosis inconclusive.
        if 'geometry_always_xy' in sql.value.lower() or '--' in sql.value or '/*' in sql.value:
            setup_or_unknown = True
        if _SENSITIVE.search(sql.value):
            sensitive.append(node.lineno)
    return sorted(set(sensitive)) if not setup_or_unknown else []
