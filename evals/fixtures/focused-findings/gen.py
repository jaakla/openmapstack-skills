"""Focused view/findings controls and isolated mutations; no model calls."""

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


def generate(root: Path, mutation: str | None = None) -> None:
    example.create(root, focused=True)
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
    elif mutation in {"expanded", "answer", "state"}:
        page = root / "dashboard.html"
        text = page.read_text()
        if mutation == "expanded":
            text = text.replace('<details data-oms-detail="evidence">', '<details data-oms-detail="evidence" open>')
        elif mutation == "answer":
            text = text.replace("data-oms-answer", "data-removed-answer")
        else:
            text = text.replace('</body>', '''<script>
document.querySelector('details').addEventListener('toggle', () => {
  document.documentElement.dataset.omsState = 'exploratory';
});
</script></body>''')
        page.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--break", dest="mutation", choices=["evidence", "missing", "run", "expanded", "answer", "state"])
    args = parser.parse_args()
    generate(args.destination, args.mutation)
