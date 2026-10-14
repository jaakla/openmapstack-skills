"""Findings artifact consistency; claim correctness still needs domain checks."""

from pathlib import Path

from . import AssertionResult, failed, load_project_yaml, passed, project_root
from .. import findings


def artifact_matches(workspace: Path, project_dir: str = ".") -> AssertionResult:
    """Declared findings resolve to the current run, evidence and Markdown body."""
    project = load_project_yaml(workspace, project_dir)
    if project is None:
        return failed("project.yaml missing", code="manifest_missing")
    if "findings" not in project:
        return failed("project does not declare findings", code="findings_undeclared")
    errors = findings.artifact_errors(project_root(workspace, project_dir), project)
    if errors:
        return failed("; ".join(errors), code="findings_inconsistent", errors=errors)
    return passed("findings match the current run and analytical artifacts")
