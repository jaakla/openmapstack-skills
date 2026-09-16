"""Complete, independently installable skill snapshots (v2); v1 stays historical."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml
from jsonschema import Draft202012Validator

from .snapshot import SnapshotError, _content_hash, _git

SCHEMA = "openmapstack-skill-snapshot/v2"
COLLECTION_SCHEMA = "openmapstack-collection/v1"
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SCHEMA_PATH = Path(__file__).parent / "schemas/skill-snapshot-v2.schema.json"


def find_collection_root(start=None):
    current = Path(start or Path.cwd()).resolve()
    return next((p for p in (current, *current.parents) if (p / "collection.json").is_file()), None)


def skill_metadata(root):
    if root.is_symlink() or (root / "SKILL.md").is_symlink():
        raise SnapshotError("skill root/entrypoint must not be a symlink")
    try:
        text = (root / "SKILL.md").read_text()
        if not text.startswith("---\n"):
            raise ValueError("missing frontmatter")
        metadata = yaml.safe_load(text.split("---", 2)[1])
        name = metadata["name"]
        version = metadata["metadata"]["version"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(version, str):
            raise ValueError("invalid skill identity")
        if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
            raise ValueError("missing skill description")
        return {"name": name, "version": version, "description": metadata["description"]}
    except (OSError, ValueError, KeyError, TypeError, IndexError, yaml.YAMLError) as exc:
        raise SnapshotError(f"invalid skill metadata in {root}: {exc}") from exc


def collection_skills(source, selected=None):
    source = Path(source)
    if source.is_symlink():
        raise SnapshotError("source must not be a symlink")
    source = source.resolve()
    if (source / "collection.json").is_symlink():
        raise SnapshotError("collection manifest must not be a symlink")
    if (source / "collection.json").is_file():
        try:
            collection = json.loads((source / "collection.json").read_text())
            if collection["schema"] != COLLECTION_SCHEMA or not isinstance(collection["version"], str):
                raise ValueError("unsupported collection manifest")
            skills = {}
            for entry in collection["skills"]:
                name = entry["name"]
                if not NAME.fullmatch(name) or name in skills or entry["path"] != f"skills/{name}":
                    raise ValueError("unsafe/duplicate skill path")
                root = source / entry["path"]
                if (source / "skills").is_symlink():
                    raise ValueError("symlinked skills directory")
                metadata = skill_metadata(root)
                if metadata["name"] != name or metadata["version"] != collection["version"]:
                    raise ValueError("collection/skill identity or version mismatch")
                skills[name] = (root, metadata)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SnapshotError(f"invalid collection: {exc}") from exc
    else:
        metadata = skill_metadata(source)
        skills = {metadata["name"]: (source, metadata)}
    chosen = list(selected) if selected else sorted(skills)
    if not chosen or len(chosen) != len(set(chosen)) or set(chosen) - skills.keys():
        raise SnapshotError("empty, duplicate or unknown skill selection")
    return {name: skills[name] for name in sorted(chosen)}


def create_collection_snapshot(source, destination, *, selected=None):
    chosen = collection_skills(source, selected)
    destination = Path(destination)
    if destination.is_symlink():
        raise SnapshotError("destination must not be a symlink")
    destination = destination.resolve()
    source = Path(source).resolve()
    if destination == source or source in destination.parents:
        raise SnapshotError("snapshot destination must be outside the source")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise SnapshotError("snapshot destination must be empty")
    payload, descriptors = {}, []
    for name, (root, metadata) in chosen.items():
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise SnapshotError(f"symlink in skill payload: {path}")
            if any(p in {".git", "__pycache__", ".DS_Store"} or p.endswith(".pyc") for p in path.relative_to(root).parts):
                continue
            if path.is_file():
                payload[f"skills/{name}/" + path.relative_to(root).as_posix()] = path.read_bytes()
        descriptors.append({**metadata, "entrypoint": f"skills/{name}/SKILL.md"})
    descriptor = {"schema": COLLECTION_SCHEMA, "version": descriptors[0]["version"],
                  "skills": [{"name": s["name"], "path": f"skills/{s['name']}"} for s in descriptors]}
    payload["collection.json"] = (json.dumps(descriptor, indent=2) + "\n").encode()
    files = [{"path": name, "sha256": "sha256:" + hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in sorted(payload.items())]
    revision = _git(source)
    try:
        status = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=source,
                                capture_output=True, text=True, timeout=10, check=False)
        if status.returncode == 0:
            revision["dirty"] = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                "collection_version": descriptor["version"], "source_git": revision, "skills": descriptors,
                "files": files, "file_count": len(files), "content_sha256": _content_hash(list(payload.items()))}
    _validate(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    for relative, content in payload.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (destination / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _validate(manifest):
    errors = list(Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).iter_errors(manifest))
    if errors:
        raise SnapshotError("invalid v2 snapshot manifest: " + errors[0].message)


def inspect_collection_snapshot(directory):
    root = Path(directory)
    if root.is_symlink() or (root / "snapshot.json").is_symlink():
        raise SnapshotError("snapshot root/manifest must not be a symlink")
    root = root.resolve()
    try:
        manifest = json.loads((root / "snapshot.json").read_text())
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"cannot read snapshot manifest: {exc}") from exc
    _validate(manifest)
    problems, seen, contents = [], set(), []
    for entry in manifest["files"]:
        relative = entry["path"]
        path = Path(relative)
        target = root / path
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative or relative in seen:
            problems.append(f"unsafe/duplicate inventory path: {relative}")
            continue
        seen.add(relative)
        if any(p.is_symlink() for p in (target, *target.parents) if p != root and root in p.parents):
            problems.append(f"symlink in snapshot: {relative}")
            continue
        if not target.is_file():
            problems.append(f"missing: {relative}")
            continue
        data = target.read_bytes()
        contents.append((relative, data))
        if len(data) != entry["bytes"] or "sha256:" + hashlib.sha256(data).hexdigest() != entry["sha256"]:
            problems.append(f"changed: {relative}")
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            problems.append(f"symlink in snapshot: {relative}")
        elif path.is_file() and relative != "snapshot.json" and relative not in seen:
            problems.append(f"extra: {relative}")
    names = [skill["name"] for skill in manifest["skills"]]
    if len(names) != len(set(names)):
        problems.append("duplicate skills")
    for skill in manifest["skills"]:
        if skill["entrypoint"] != f"skills/{skill['name']}/SKILL.md" or skill["entrypoint"] not in seen or skill["version"] != manifest["collection_version"]:
            problems.append("skill descriptor does not match the collection inventory")
    if "collection.json" not in seen or len(seen) != manifest["file_count"]:
        problems.append("incomplete collection inventory")
    if not problems:
        for skill in manifest["skills"]:
            actual = skill_metadata(root / "skills" / skill["name"])
            if any(actual[key] != skill[key] for key in actual):
                problems.append("skill descriptor differs from installed metadata")
        collection = json.loads(dict(contents)["collection.json"])
        expected = {"schema": COLLECTION_SCHEMA, "version": manifest["collection_version"],
                    "skills": [{"name": s["name"], "path": f"skills/{s['name']}"} for s in manifest["skills"]]}
        if collection != expected:
            problems.append("collection.json differs from snapshot selection")
    digest = _content_hash(contents)
    if digest != manifest["content_sha256"]:
        problems.append("content_sha256 does not match the inventory")
    return {"schema": "openmapstack-skill-snapshot-inspection/v2", "snapshot": str(root), "intact": not problems,
            "content_sha256": manifest["content_sha256"], "recomputed_sha256": digest,
            "file_count": len(seen), "problems": problems, "manifest": manifest}
