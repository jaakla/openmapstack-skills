"""Shared manifest declaration rules, independent of execution runtimes."""

from __future__ import annotations

from datetime import date, datetime


PLACEHOLDERS = {"", "todo", "tbd", "n/a", "none", "null", "...", "https://..."}


def present(value: object) -> bool:
    """Whether a declaration has a non-placeholder value."""
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized not in PLACEHOLDERS and not normalized.startswith("todo-") and not normalized.startswith("todo ")
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    if isinstance(value, (date, datetime)):
        return True
    return True


def override_evidence_valid(evidence: object) -> bool:
    """Require a nonempty list whose entries identify non-placeholder evidence.

    A mapping identifies evidence through value, source, or title, in that
    order; plain references are also supported. This checks declaration
    completeness, not whether the referenced evidence proves the override.
    """
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if isinstance(item, dict):
            candidate = item.get("value") or item.get("source") or item.get("title")
        else:
            candidate = item
        if not present(candidate):
            return False
    return True
