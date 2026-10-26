"""Tartu's finalizer must attest every declared implementation dependency."""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from openmapstack.integrity import canonical_file_set_hash, declared_input_paths, declared_output_paths
from openmapstack.validation import validate_project

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/tartu-development"


class TartuRunEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oms-tartu-run-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in ("pipeline.py", "project.yaml", "dashboard-template.html", "routing.py", "qgis_delivery.py", "requirements.txt"):
            shutil.copy(EXAMPLE / relative, self.root / relative)
        # Only the finalizer executes; no GIS engine, routing or network is needed.
        spec = importlib.util.spec_from_file_location("tartu_run_evidence", self.root / "pipeline.py")
        self.pipeline = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "duckdb": SimpleNamespace(DuckDBPyConnection=object, __version__="fixture"),
            "pyproj": SimpleNamespace(__version__="fixture"),
        }):
            spec.loader.exec_module(self.pipeline)
        for relative in ("runs", "validation", "data/source", "data/overrides"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        (self.root / "data/source/synthetic.txt").write_text("synthetic source")
        (self.root / "data/overrides/synthetic.txt").write_text("synthetic override")
        for relative in declared_output_paths(self.pipeline.PROJECT):
            output = self.root / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("synthetic output")
        # Legacy companion artifacts also participate in the output inventory.
        for relative in ("project.qgz", "validation/routing-evidence.json"):
            (self.root / relative).write_text("synthetic companion artifact")

    def finalize(self):
        report = {"run_id": "run-20261008-000000", "status": "warning", "checks": []}
        self.pipeline.finalize_run(report, [], "2026-10-08T00:00:00+00:00")
        record = json.loads((self.root / "runs/run-20261008-000000.json").read_text())
        return report, record

    def run_check(self):
        return next(check for check in validate_project(self.root).checks if check.id == "runs.latest")

    def test_finalizer_inventories_declared_scripts_and_dependency_directories(self):
        (self.root / "helpers").mkdir()
        (self.root / "helpers/settings.json").write_text('{"fixture": true}')
        self.pipeline.PROJECT["runtime"]["implementation"]["dependencies"].extend(["helpers", "qgis_delivery.py"])
        report, record = self.finalize()
        inputs = {entry["path"] for entry in record["inputs"]}
        self.assertIn("qgis_delivery.py", inputs)
        self.assertIn("dashboard-template.html", inputs)
        self.assertIn("helpers/settings.json", inputs)
        self.assertEqual(len(inputs), len(record["inputs"]))
        self.assertEqual(inputs, set(declared_input_paths(self.root, self.pipeline.PROJECT)))
        expected = canonical_file_set_hash(self.root, inputs)
        self.assertEqual(record["inputs_hash"], expected)
        self.assertEqual(report["inputs_hash"], expected)
        self.assertEqual(self.pipeline.PROJECT["runs"]["latest"]["inputs_hash"], expected)
        check = self.run_check()
        self.assertEqual(check.status, "passed", check.message)

    def test_qgis_dependency_drift_fails_until_a_new_run_attests_it(self):
        _, original = self.finalize()
        self.assertEqual(self.run_check().status, "passed")
        with (self.root / "qgis_delivery.py").open("a") as stream:
            stream.write("\n# synthetic implementation change\n")
        check = self.run_check()
        self.assertEqual(check.status, "failed", check.message)
        self.assertIn("run input hash mismatch: qgis_delivery.py", check.message)
        _, rebuilt = self.finalize()
        self.assertNotEqual(rebuilt["inputs_hash"], original["inputs_hash"])
        self.assertEqual(rebuilt["outputs_hash"], original["outputs_hash"])
        self.assertEqual(self.run_check().status, "passed")

    def test_findings_and_all_table_downloads_enter_the_final_inventory(self):
        from openmapstack.findings import artifact_errors
        from openmapstack.integrity import sha256_file

        self.pipeline.PROJECT["outputs"]["summary"] = {
            "path": "data/derived/summary.csv", "kind": "table", "format": "CSV",
            "generated_by": "render_findings", "downloads": ["csv", "json"],
        }
        for extension in ("csv", "json"):
            (self.root / f"data/derived/summary.{extension}").write_text("synthetic table " + extension)
        report = {"run_id": "run-20261008-000000", "status": "warning", "checks": []}
        items = [{"id": "summary", "statement": "Synthetic finalizer test, not a factual result.", "evidence": ["summary"]}]
        self.pipeline.finalize_run(report, [], "2026-10-08T00:00:00+00:00", findings=items)
        record = json.loads((self.root / "runs/run-20261008-000000.json").read_text())
        inventory = {item["path"]: item["sha256"] for item in record["outputs"]}
        self.assertEqual(inventory["findings.md"], sha256_file(self.root / "findings.md"))
        self.assertIn("data/derived/summary.json", inventory)
        self.assertEqual(artifact_errors(self.root, self.pipeline.PROJECT), [])
        (self.root / "data/derived/summary.json").write_text("mutated secondary download")
        self.assertIn("hash differs", "; ".join(artifact_errors(self.root, self.pipeline.PROJECT)))


class CommittedTartuEnvironmentTests(unittest.TestCase):
    def test_manifest_requirements_and_run_attestation_agree_on_duckdb(self):
        from packaging.requirements import Requirement

        project = yaml.safe_load((EXAMPLE / 'project.yaml').read_text())
        record = json.loads((EXAMPLE / project['runs']['latest']['record']['path']).read_text())
        pinned = str(project['runtime']['environment']['duckdb'])
        self.assertEqual(pinned, record['environment']['duckdb'])
        requirement = next(Requirement(line) for line in (EXAMPLE / 'requirements.txt').read_text().splitlines()
                           if line.startswith('duckdb'))
        self.assertTrue(requirement.specifier.contains(pinned), (pinned, str(requirement)))
