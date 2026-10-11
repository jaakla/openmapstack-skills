"""Create an independent Observable delivery sample from a checked-in city snapshot."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml

from openmapstack.integration import definition_hash, steps_hash
from openmapstack.integrity import sha256_file

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent
CITIES = {"tartu": "tartu-development", "nyc": "nyc-private-mobility"}


def create(destination: Path, city: str) -> Path:
    if city not in CITIES:
        raise ValueError("choose tartu or nyc")
    destination = destination.resolve()
    if destination == HERE or destination.is_relative_to(HERE):
        raise ValueError("use a separate workspace")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must be empty; existing work is never overwritten")
    destination.mkdir(parents=True, exist_ok=True)
    upstream = EXAMPLES / CITIES[city]
    original = yaml.safe_load((upstream / "project.yaml").read_text())
    for name in ("pipeline.py", "README.md"):
        shutil.copyfile(HERE / name, destination / name)
    shutil.copytree(HERE / "observable", destination / "observable",
                    ignore=shutil.ignore_patterns("node_modules", "dist", ".observablehq"))
    shutil.copyfile(HERE / city / "index.md", destination / "observable/src/index.md")
    source = destination / "data/source"
    source.mkdir(parents=True)
    for name in ("dashboard.html", "project.yaml"):
        shutil.copyfile(upstream / name, source / name)
    project = yaml.safe_load((HERE / "project.yaml").read_text())
    project["project"].update(id=city + "-observable", title=("Tartu" if city == "tartu" else "NYC") + " — Observable snapshot explorer",
        question="Explore the recorded city results without changing the accepted analysis.",
        created_at=str(original["project"]["updated_at"]), updated_at=str(original["project"]["updated_at"]))
    project["sample"] = {"city": city, "upstream_example": CITIES[city],
                         "upstream_run": original["runs"]["latest"]["id"]}
    project["processing"]["analysis_crs"] = original["processing"]["analysis_crs"]
    project["outputs"]["metrics"]["table"]["columns"][-1].update(
        unit="m²" if city == "tartu" else "score points", nullable=city == "nyc")
    project["interpretation"] = {"objective": "Re-export and explore the checked-in city dashboard snapshot. "
        "The original spatial analysis is owned by the upstream example, not replayed here.",
        "assumptions": [{"id": "snapshot", "statement": "Filters only narrow precomputed snapshot rows; "
            "scores, distances, catchments and scenarios are not recalculated.",
            "rationale": "This sample demonstrates Observable delivery independently of GIS runtimes and warehouse credentials."},
            *original["interpretation"]["assumptions"]]}
    project["warnings"] = original.get("warnings", [])
    project["sources"] = {}
    for key, name in (("snapshot", "dashboard.html"), ("upstream_manifest", "project.yaml")):
        project["sources"][key] = {
            "role": "authoritative_input", "provider": "OpenMapStack city examples",
            "dataset": CITIES[city] + "/" + name,
            "source_url": "https://github.com/jaakla/openmapstack-skills/tree/main/examples/" + CITIES[city],
            "access": {"method": "local", "retrieved_at": str(original["project"]["updated_at"]),
                       "file": {"name": name, "format": "HTML" if key == "snapshot" else "YAML"}},
            "version": {"identifier": original["runs"]["latest"]["id"]},
            "selection": {"filter": "Complete checked-in public presentation snapshot"},
            "pin": {"class": "local_snapshot", "path": "data/source/" + name,
                    "sha256": sha256_file(source / name), "captured_at": str(original["project"]["updated_at"])},
            "license": {"name": "Mixed upstream terms; see original source manifest and visible provenance",
                        "url": "https://github.com/jaakla/openmapstack-skills/tree/main/examples/" + CITIES[city]},
            "schema": {"crs": "EPSG:4326", "key": "cadastral_id" if city == "tartu" else "h3_cell"},
            "rationale": "Pinned public presentation snapshot; no customer records or warehouse access.",
        }
    binding = {"id": "observable", "owner": "observable", "role": "presentation",
               "definition": "observable", "steps": ["render"]}
    binding.update(sha256=definition_hash(destination, "observable"),
                   steps_sha256=steps_hash(project, ["render"]))
    project["integrations"]["bindings"] = [binding]
    path = destination / "project.yaml"
    path.write_text(yaml.safe_dump(project, sort_keys=False, allow_unicode=True))
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--city", choices=CITIES, required=True)
    args = parser.parse_args()
    print(create(args.destination, args.city))
