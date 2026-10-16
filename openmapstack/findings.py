"""Pipeline-authored findings: readable Markdown with structured evidence.

The writer records claims supplied by the analysis; it does not infer answers.
The checker establishes artifact consistency, not the truth of those claims.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import yaml

from .delivery import shared_semantics
from .integrity import sha256_file
from .project import get_in, project_path
from .schema import load_packaged_schema, validation_errors

SCHEMA = "openmapstack-findings/v1"


def declaration_errors(root: Path, project: dict) -> list[str]:
    declaration = project.get("findings")
    if declaration is None and "findings" not in project:
        return []
    if not isinstance(declaration, dict) or declaration.get("schema") != SCHEMA:
        return [f"findings must declare schema: {SCHEMA}"]
    key = declaration.get("output")
    outputs = project.get("outputs") or {}
    if not isinstance(outputs, dict):
        return ["findings.output requires declared outputs"]
    output = outputs.get(key) if isinstance(key, str) else None
    if not isinstance(output, dict) or output.get("kind") != "document":
        return ["findings.output must reference a declared document output"]
    path = project_path(root, output.get("path"))
    if path is None or path.suffix.lower() != ".md":
        return ["findings output must have a safe project-relative .md path"]
    if any(name != key and isinstance(other, dict) and project_path(root, other.get("path")) == path
           for name, other in outputs.items()):
        return ["findings output must not alias another output"]
    return []


def _context_hash(project: dict) -> str:
    encoded = json.dumps(shared_semantics(project), sort_keys=True, default=str, ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validation(report: dict) -> dict:
    return {"status": report["status"], "checks": [
        {"id": check["id"], "status": check["status"]} for check in report["checks"]
    ]}


def _link(root: Path, document: Path, target: Path) -> str:
    return quote(Path(os.path.relpath(target, document.parent)).as_posix(), safe="/.-_")


def render(root: Path, document: Path, metadata: dict) -> str:
    """Render the body from the same metadata agents can parse as frontmatter."""
    lines = ["# Findings", "", metadata["question"], "",
             f"Scope: {metadata['scope']}. Run: `{metadata['run_id']}`. "
             f"Validation: **{metadata['validation']['status']}**.", ""]
    for item in metadata["findings"]:
        lines.extend([f"## {item['id']}", "", item["statement"], "", "Evidence:", ""])
        for key in item["evidence"]:
            entry = metadata["evidence"][key]
            href = _link(root, document, root / entry["definition"]["path"])
            lines.append(f"- [{key}]({href})")
        for limitation in item.get("limitations", []):
            lines.extend(["", f"Limitation: {limitation}"])
        lines.append("")
    lines.extend(["## Assumptions and limitations", ""])
    for assumption in metadata["assumptions"]:
        lines.append(f"- {assumption['statement']} {assumption['rationale']}")
    for warning in metadata["warnings"]:
        lines.append(f"- {warning['statement']}")
    lines.extend(["", f"[Project, sources and definitions]({_link(root, document, root / 'project.yaml')})",
                  f" · [Validation report]({_link(root, document, root / metadata['validation_report'])})", ""])
    return "\n".join(lines)


def write_findings(root: Path, project: dict, *, report: dict, scope: str, findings: list[dict],
                   validation_report: str = "validation/latest-report.json") -> Path:
    """Write before final output hashing, with this execution's report/run ID.

    ``findings`` contains stable IDs, pipeline-authored statements, evidence
    output keys and optional limitations. Units/definitions come from outputs.
    """
    errors = declaration_errors(root, project)
    if "findings" not in project:
        errors.append("declare findings before writing them")
    if errors:
        raise ValueError("; ".join(errors))
    if project_path(root, validation_report) is None:
        raise ValueError("validation_report must have a safe project-relative path")
    schema = load_packaged_schema("findings-v1.schema.json")
    errors = validation_errors(findings, {"$defs": schema["$defs"], **schema["properties"]["findings"]})
    if errors:
        raise ValueError("; ".join(errors))
    path = project_path(root, project["outputs"][project["findings"]["output"]]["path"])
    evidence = {}
    for item in findings:
        for key in item.get("evidence", []):
            output = (project.get("outputs") or {}).get(key) if isinstance(key, str) else None
            if not isinstance(output, dict) or output.get("kind", "geodata") not in {"geodata", "table"}:
                raise ValueError(f"finding evidence {key!r} must reference an analytical output")
            target = project_path(root, output.get("path"))
            if target is None or not target.is_file():
                raise ValueError(f"finding evidence {key!r} is missing or unsafe")
            evidence[key] = {"definition": output, "sha256": sha256_file(target)}
    metadata = {
        "schema": SCHEMA, "project_id": project["project"]["id"],
        "question": project["project"]["question"], "run_id": report["run_id"],
        "scope": scope, "validation": _validation(report),
        "validation_report": validation_report,
        "context_sha256": _context_hash(project),
        "assumptions": get_in(project, "interpretation", "assumptions", default=[]),
        "warnings": project.get("warnings") or [], "findings": findings, "evidence": evidence,
    }
    errors = validation_errors(metadata, load_packaged_schema("findings-v1.schema.json"))
    ids = [item["id"] for item in findings]
    if len(ids) != len(set(ids)):
        errors.append("finding IDs must be unique")
    if errors:
        raise ValueError("; ".join(errors))
    text = "---\n" + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True) + "---\n" + render(root, path, metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def artifact_errors(root: Path, project: dict) -> list[str]:
    errors = declaration_errors(root, project)
    if errors or "findings" not in project:
        return errors
    path = project_path(root, project["outputs"][project["findings"]["output"]]["path"])
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return ["findings must start with YAML frontmatter"]
        header, body = text[4:].split("\n---\n", 1)
        metadata = yaml.safe_load(header)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return [f"cannot read findings: {exc}"]
    errors = validation_errors(metadata, load_packaged_schema("findings-v1.schema.json"))
    if errors:
        return errors
    for key, expected in {
        "project_id": get_in(project, "project", "id"), "question": get_in(project, "project", "question"),
        "run_id": get_in(project, "runs", "latest", "id"), "context_sha256": _context_hash(project),
        "assumptions": get_in(project, "interpretation", "assumptions", default=[]),
        "warnings": project.get("warnings") or [],
    }.items():
        if metadata[key] != expected:
            errors.append(f"findings {key} differs from the canonical project/run")
    report_path = project_path(root, get_in(project, "runs", "latest", "validation_report", "path"))
    if metadata["validation"]["status"] != get_in(project, "runs", "latest", "status"):
        errors.append("findings validation status differs from the canonical run")
    try:
        report = json.loads(report_path.read_text()) if report_path else {}
        if (report.get("run_id") != metadata["run_id"] or metadata["validation"] != _validation(report)
                or report_path != project_path(root, metadata["validation_report"])):
            errors.append("findings validation differs from the canonical report")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        errors.append("findings validation report is missing or invalid")
    ids = [item["id"] for item in metadata["findings"]]
    if len(ids) != len(set(ids)):
        errors.append("finding IDs must be unique")
    referenced = {key for item in metadata["findings"] for key in item["evidence"]}
    if referenced != set(metadata["evidence"]):
        errors.append("findings evidence inventory differs from finding references")
    for key, evidence in metadata["evidence"].items():
        output = (project.get("outputs") or {}).get(key)
        if not isinstance(output, dict) or output.get("kind", "geodata") not in {"geodata", "table"}:
            errors.append(f"findings evidence {key!r} does not resolve to an analytical output")
            continue
        target = project_path(root, output.get("path"))
        if evidence["definition"] != output or target is None or not target.is_file():
            errors.append(f"findings evidence {key!r} is missing or its definition changed")
        elif sha256_file(target) != evidence["sha256"]:
            errors.append(f"findings evidence {key!r} hash differs from the result file")
    if not errors and body != render(root, path, metadata):
        errors.append("findings Markdown differs from its structured metadata")
    return errors
