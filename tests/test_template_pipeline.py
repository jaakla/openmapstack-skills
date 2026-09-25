"""The shipped pipeline template must own the manifest's run pointer.

At candidate 861b58b a live material trial patched `runs.latest` into
project.yaml by hand after each run, because the template wrote no run
record and never touched the manifest. The clean rerun then wrote a new
timestamped record and the rebuilt manifest pointed at one that did not
exist. These tests run the template itself.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from openmapstack.integrity import canonical_file_set_hash
from tests.evals.helpers import make_workspace, minimal_project, write_project

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "pipeline.py"


def _workspace() -> Path:
    workspace = make_workspace()
    write_project(workspace, minimal_project())
    (workspace / "data" / "source").mkdir(parents=True)
    (workspace / "data" / "source" / "parcels.geojson").write_text('{"type": "FeatureCollection", "features": []}')
    # The template's analytical steps are placeholders; stand in for their output.
    (workspace / "data" / "derived").mkdir(parents=True)
    (workspace / "data" / "derived" / "final.json").write_text('{"type": "FeatureCollection", "features": []}')
    shutil.copy(TEMPLATE, workspace / "pipeline.py")
    return workspace


def _run(workspace: Path) -> None:
    subprocess.run([sys.executable, "pipeline.py"], cwd=workspace, check=True, capture_output=True, text=True)


class TemplatePipelineOwnsRunPointerTests(unittest.TestCase):
    def test_manifest_points_at_the_record_the_run_wrote(self) -> None:
        workspace = _workspace()
        _run(workspace)
        project = yaml.safe_load((workspace / "project.yaml").read_text())
        latest = project["runs"]["latest"]
        record_path = workspace / latest["record"]["path"]
        self.assertTrue(record_path.is_file(), latest)
        self.assertEqual(record_path.name, f"{latest['id']}.json")
        self.assertRegex(latest["id"], r"^run-\d{8}-\d{6}$")
        record = json.loads(record_path.read_text())
        report = json.loads((workspace / "validation" / "latest-report.json").read_text())
        self.assertEqual(record["run_id"], latest["id"])
        self.assertEqual(report["run_id"], latest["id"])

    def test_recorded_hashes_are_the_canonical_file_set_hashes(self) -> None:
        workspace = _workspace()
        _run(workspace)
        latest = yaml.safe_load((workspace / "project.yaml").read_text())["runs"]["latest"]
        inputs = ["data/source/parcels.geojson", "pipeline.py"]
        self.assertEqual(latest["inputs_hash"], canonical_file_set_hash(workspace, inputs))
        self.assertEqual(latest["outputs_hash"], canonical_file_set_hash(workspace, ["data/derived/final.json"]))

    def test_a_warning_run_does_not_leave_the_project_validated(self) -> None:
        workspace = _workspace()
        _run(workspace)
        project = yaml.safe_load((workspace / "project.yaml").read_text())
        self.assertEqual(project["runs"]["latest"]["status"], "warning")
        self.assertEqual(project["project"]["status"], "warning")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
