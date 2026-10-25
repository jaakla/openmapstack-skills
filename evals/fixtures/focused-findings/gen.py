"""Pipeline findings controls and isolated mutations; no model calls."""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("focused_example", ROOT / "examples/delivery-profiles/create.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def generate(root: Path, mutation: str | None = None, *, downloads: bool = False) -> None:
    path = example.create(root)
    if downloads:
        project = yaml.safe_load(path.read_text())
        project["outputs"]["areas"]["downloads"] = ["csv", "json"]
        path.write_text(yaml.safe_dump(project, sort_keys=False))
        script = root / "pipeline.py"
        source = script.read_text().replace('    ids = ", ".join', '''    table.with_suffix(".json").write_text(json.dumps([
        {"id": f["properties"]["id"], "area_m2": f["properties"]["area_m2"]} for f in chosen
    ]) + "\\n")
    ids = ", ".join''')
        script.write_text(source)
    subprocess.run([sys.executable, str(root / "pipeline.py")], check=True)
    if mutation == "evidence":
        (root / "data/derived/areas.csv").write_text("id,area_m2\nlarge,999999\n")
    elif mutation == "missing":
        (root / "findings.md").unlink()
    elif mutation == "run":
        findings = root / "findings.md"
        header, body = findings.read_text()[4:].split("\n---\n", 1)
        metadata = yaml.safe_load(header)
        metadata["run_id"] = "run-stale"
        findings.write_text("---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + body)
    elif mutation == "download":
        (root / "data/derived/areas.json").write_text('[{"id": "large", "area_m2": 999999}]\n')
    elif mutation == "missing-download":
        (root / "data/derived/areas.json").unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--downloads", action="store_true", help="generate a secondary JSON table download")
    parser.add_argument("--break", dest="mutation", choices=["evidence", "missing", "run", "download", "missing-download"])
    args = parser.parse_args()
    generate(args.destination, args.mutation, downloads=args.downloads)
