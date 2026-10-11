"""Replay public presentation snapshots and build a real Observable Framework bundle.

This delivery pipeline never queries a service or recomputes spatial results.
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from openmapstack import delivery, integration
from openmapstack.checks.delivery import evidence_matches
from openmapstack.checks.integration import evidence_matches as integration_matches
from openmapstack.integrity import (canonical_file_set_hash, declared_input_paths,
                                    declared_output_paths, file_inventory, sha256_file)


def constant(document: str, name: str) -> dict:
    match = re.search(r"^const " + re.escape(name) + r" = (.*);$", document, re.MULTILINE)
    if not match:
        raise ValueError(f"snapshot lacks JSON constant {name}")
    return json.loads(match[1])


def export(root: Path, project: dict) -> dict:
    for source in project["sources"].values():
        pin = source["pin"]
        if sha256_file(root / pin["path"]) != pin["sha256"]:
            raise ValueError("pinned city snapshot changed: " + pin["path"])
    upstream = yaml.safe_load((root / "data/source/project.yaml").read_text())
    document = (root / "data/source/dashboard.html").read_text()
    city = project["sample"]["city"]
    if city == "tartu":
        view = constant(document, "VIEW")
        features, context, points = (constant(document, key) for key in ("CANDIDATES", "ROADS", "POIS"))
        run_id = view["run"]["id"]
    else:
        match = re.search(r'<script type="application/json" id="dashboard-data">(.*?)</script>', document, re.DOTALL)
        if not match:
            raise ValueError("snapshot lacks dashboard-data JSON")
        view = json.loads(match[1])
        features, context, points = (view[key] for key in ("zones", "hubs", "fleet_points"))
        run_id = view["run_id"]
    if run_id != project["sample"]["upstream_run"]:
        raise ValueError("city dashboard and upstream manifest run IDs disagree")
    if not features["features"]:
        raise ValueError("empty city snapshot")
    for key, value in (("features", features), ("context", context), ("points", points)):
        path = root / project["outputs"][key]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")
    rows = []
    for feature in features["features"]:
        p = feature["properties"]
        rows.append([p["cadastral_id"], p["address"], p["suitability_tier"], p["area_m2"]] if city == "tartu" else
                    [p["h3_cell"], p["zone_name"], p["borough"], p["final_score"]])
    if len({row[0] for row in rows}) != len(rows):
        raise ValueError("duplicate city snapshot identities")
    with (root / project["outputs"]["metrics"]["path"]).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "label", "category", "value"])
        writer.writerows(rows)
    notes = [
        "OpenMapStack city examples. Generated with AI using the free OpenMapStack toolkit: " + project["project"]["generated_with"]["url"],
        f"Author: {project['project']['author']['name']} ({project['project']['author']['email']}).",
        f"Recorded upstream analysis: {run_id}; completed {upstream['runs']['latest']['completed_at']}. "
        f"Source snapshot SHA-256: {project['sources']['snapshot']['pin']['sha256']}.",
        "This Observable sample re-exports a public presentation snapshot. It does not rerun the upstream spatial analysis. "
        "Coordinates shown: EPSG:4326. Metric calculations retain the upstream analysis CRS: " + upstream["processing"]["analysis_crs"],
    ]
    for source in upstream["sources"].values():
        access = source.get("access", {})
        captured = access.get("retrieved_at", access.get("downloaded_at", "See upstream manifest"))
        notes.append(f"{source['provider']} — {source['dataset']}. Version: {source['version']['identifier']}. "
            f"License: {source['license']['name']}. CRS: {source.get('schema', {}).get('crs', 'See upstream manifest')}. Source: {source['source_url']}. "
            f"Captured: {captured}. Access: {access.get('method', 'See upstream manifest')}.")
    notes.extend(a["statement"] + " " + a["rationale"] for a in project["interpretation"]["assumptions"])
    notes.extend(w["statement"] for w in project.get("warnings", []))
    notes.extend("Recorded upstream override: " + json.dumps(o, ensure_ascii=False, default=str)
                 for o in upstream.get("overrides", []))
    return {"notes": notes, "categories": sorted({r[2] for r in rows}), "row_count": len(rows)}


def render(root: Path, project: dict, info: dict) -> None:
    work = root / "work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="observable-", dir=work) as temporary:
        stage = Path(temporary) / "app"
        shutil.copytree(root / "observable", stage)
        (stage / "metadata.json").write_text(delivery.metadata_json(root, project, project["delivery"]["targets"][0]))
        (stage / "src/provenance.json").write_text(json.dumps(info, ensure_ascii=False))
        for key in project["delivery"]["targets"][0]["inputs"]:
            path = root / project["outputs"][key]["path"]
            shutil.copyfile(path, stage / "src" / path.name)
        env = {**os.environ, "OBSERVABLE_TELEMETRY_DISABLE": "1"}
        with (work / "observable-build.log").open("w") as log:
            for command in (["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], ["npm", "run", "build"]):
                subprocess.run(command, cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        bundle = root / "views/observable"
        if bundle.exists():
            shutil.rmtree(bundle)
        shutil.copytree(stage / "dist", bundle)
        # Stable downloads accompany Framework's content-addressed attachments.
        for key in project["delivery"]["targets"][0]["inputs"]:
            path = root / project["outputs"][key]["path"]
            shutil.copyfile(path, bundle / path.name)


def main(root: Path | None = None) -> None:
    root = Path(__file__).resolve().parent if root is None else root.resolve()
    project = yaml.safe_load((root / "project.yaml").read_text())
    started = datetime.datetime.now(datetime.timezone.utc)
    info = export(root, project)
    render(root, project, info)
    delivery.write_evidence(root, project)
    integration.write_evidence(root, project)
    result = evidence_matches(root, "observable")
    if result.status != "passed":
        raise ValueError(result.detail)
    result = integration_matches(root)
    if result.status != "passed":
        raise ValueError(result.detail)
    checks = [{"id": name, "status": "passed"} for name in project["validation"]["required"]]
    inputs, outputs = declared_input_paths(root, project), declared_output_paths(project)
    hashes = {"inputs_hash": canonical_file_set_hash(root, inputs), "outputs_hash": canonical_file_set_hash(root, outputs)}
    completed = datetime.datetime.now(datetime.timezone.utc).isoformat()
    run_id = started.strftime("run-%Y%m%d-%H%M%S-%f")
    latest = {"id": run_id, "status": "passed", "started_at": started.isoformat(), "completed_at": completed,
              **hashes, "record": {"path": f"runs/{run_id}.json"},
              "validation_report": {"path": "validation/latest-report.json"}}
    (root / "runs").mkdir(exist_ok=True)
    (root / "validation").mkdir(exist_ok=True)
    (root / "validation/latest-report.json").write_text(json.dumps({"run_id": run_id, "status": "passed", **hashes, "checks": checks}, indent=2) + "\n")
    record = {"run_id": run_id, "status": "passed", "started_at": started.isoformat(), "completed_at": completed,
              **hashes, "inputs": file_inventory(root, inputs), "outputs": file_inventory(root, outputs),
              "environment": {"python": platform.python_version(), "node": subprocess.check_output(["node", "--version"], text=True).strip(),
                              "observable_framework": "1.13.4"}}
    (root / latest["record"]["path"]).write_text(json.dumps(record, indent=2) + "\n")
    project["runs"]["latest"] = latest
    project["project"]["status"] = "validated"
    (root / "project.yaml").write_text(yaml.safe_dump(project, sort_keys=False, allow_unicode=True))
    print(f"Built {project['sample']['city']} Observable sample ({info['row_count']} snapshot rows)")


if __name__ == "__main__":
    main()
