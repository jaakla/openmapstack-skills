"""Findings retain usable evidence without requiring a dashboard to show it all."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from openmapstack.findings import artifact_errors, declaration_errors, write_findings
from openmapstack.checks.findings import artifact_matches
from openmapstack.integrity import declared_output_paths, sha256_file
from openmapstack.validation import validate_project
from openmapstack.verify import verify_project
from tests.test_delivery import example


class FindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = example.create(self.root)
        subprocess.run([sys.executable, str(self.root / "pipeline.py")], check=True, capture_output=True)
        self.project = yaml.safe_load(self.path.read_text())
        self.file = self.root / "findings.md"
        self.original = self.file.read_text()

    def metadata(self):
        return yaml.safe_load(self.file.read_text()[4:].split("\n---\n", 1)[0])

    def edit_metadata(self, change):
        metadata = self.metadata()
        change(metadata)
        body = self.file.read_text()[4:].split("\n---\n", 1)[1]
        self.file.write_text("---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + body)

    def test_readable_machine_metadata_and_run_inventory_share_real_results(self):
        metadata = self.metadata()
        self.assertIn("large", metadata["findings"][0]["statement"])
        self.assertEqual(metadata["run_id"], self.project["runs"]["latest"]["id"])
        self.assertEqual(metadata["evidence"]["areas"]["definition"]["table"]["columns"][1]["unit"], "m²")
        self.assertIn("[areas](data/derived/areas.csv)", self.original)
        self.assertEqual(artifact_matches(self.root).status, "passed")
        self.assertIn("findings.md", declared_output_paths(self.project))
        record = json.loads((self.root / self.project["runs"]["latest"]["record"]["path"]).read_text())
        self.assertIn("findings.md", {entry["path"] for entry in record["outputs"]})
        self.assertEqual(validate_project(self.path).status, "passed")
        plan = verify_project(self.path)
        self.assertTrue(any(c.name == "findings.artifact_matches" for c in plan.checks))

    def test_changed_or_missing_evidence_is_detected(self):
        evidence = self.root / "data/derived/areas.csv"
        evidence.write_text("id,area_m2\nlarge,999999\n")
        self.assertIn("hash differs", "; ".join(artifact_errors(self.root, self.project)))
        evidence.unlink()
        self.assertIn("missing", "; ".join(artifact_errors(self.root, self.project)))

    def test_every_table_download_is_hashed_linked_and_checked(self):
        # A minimal XLSX workbook keeps this byte-integrity regression independent
        # of optional Excel readers; table semantics have their own checks.
        download = self.root / "data/derived/areas.xlsx"
        parts = {
            "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
            "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
            "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Areas" sheetId="1" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>id</t></is></c><c r="B1" t="inlineStr"><is><t>area_m2</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>large</t></is></c><c r="B2"><v>20000</v></c></row></sheetData></worksheet>',
        }
        with zipfile.ZipFile(download, "w") as archive:
            for name, text in parts.items():
                archive.writestr(name, text)
        self.project["outputs"]["areas"]["downloads"] = ["csv", "xlsx"]
        self.path.write_text(yaml.safe_dump(self.project, sort_keys=False))
        report = json.loads((self.root / "validation/latest-report.json").read_text())
        write_findings(self.root, self.project, report=report, scope="all input",
                       findings=self.metadata()["findings"])
        self.assertEqual(self.metadata()["evidence"]["areas"]["files"], [
            {"path": relative, "sha256": sha256_file(self.root / relative)}
            for relative in ("data/derived/areas.csv", "data/derived/areas.xlsx")])
        self.assertIn("[areas (xlsx)](data/derived/areas.xlsx)", self.file.read_text())
        self.assertEqual(artifact_matches(self.root).status, "passed")
        primary_hash = sha256_file(self.root / "data/derived/areas.csv")
        healthy_download = download.read_bytes()
        download.write_bytes(healthy_download + b"modified")
        result = artifact_matches(self.root)
        self.assertEqual((result.status, result.data["code"]), ("failed", "findings_inconsistent"))
        self.assertIn("areas.xlsx", result.detail)
        self.assertIn("hash differs", result.detail)
        download.write_bytes(healthy_download)
        self.assertEqual(artifact_matches(self.root).status, "passed")
        download.unlink()
        self.assertIn("missing", artifact_matches(self.root).detail)
        self.assertEqual(sha256_file(self.root / "data/derived/areas.csv"), primary_hash)
        with self.assertRaisesRegex(ValueError, "missing or unsafe"):
            write_findings(self.root, self.project, report=report, scope="all input",
                           findings=self.metadata()["findings"])

    def test_evidence_file_inventory_must_match_declared_paths_exactly(self):
        mutations = [
            lambda files: files.clear(),
            lambda files: files.append(copy.deepcopy(files[0])),
            lambda files: files[0].update(path="../outside.csv"),
            lambda files: files.append({"path": "extra.csv", "sha256": files[0]["sha256"]}),
            lambda files: files[0].update(sha256="invalid"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.file.write_text(self.original)
                self.edit_metadata(lambda m: mutation(m["evidence"]["areas"]["files"]))
                self.assertEqual(artifact_matches(self.root).status, "failed")

    def test_stale_run_context_definitions_and_prose_fail(self):
        mutations = [
            lambda m: m.update(run_id="run-old"),
            lambda m: m.update(question="A different question?"),
            lambda m: m["validation"].update(status="warning"),
            lambda m: m["evidence"]["areas"]["definition"]["table"]["columns"][1].update(unit="km²"),
            lambda m: m["evidence"]["areas"]["definition"].update(path={"invalid": True}),
            lambda m: m["findings"][0].update(statement="Every parcel qualifies."),
            lambda m: m["findings"][0].update(evidence=["undeclared"]),
            lambda m: m["findings"].append(copy.deepcopy(m["findings"][0])),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.file.write_text(self.original)
                self.edit_metadata(mutate)
                result = artifact_matches(self.root)
                self.assertEqual((result.status, result.data["code"]), ("failed", "findings_inconsistent"))
        self.file.write_text(self.original.replace("# Findings", "# Invented findings"))
        self.assertIn("Markdown differs", "; ".join(artifact_errors(self.root, self.project)))
        self.file.write_text(self.original)
        self.project["processing"]["steps"][1]["minimum_area_m2"] = 50000
        self.assertIn("context_sha256", "; ".join(artifact_errors(self.root, self.project)))

    def test_malformed_or_missing_artifact_fails_without_crashing(self):
        for content in ("No frontmatter", "---\n[bad, shape]\n---\n", "---\n{bad yaml\n---\n"):
            self.file.write_text(content)
            self.assertEqual(artifact_matches(self.root).status, "failed")
        self.file.unlink()
        self.assertEqual(artifact_matches(self.root).status, "failed")
        self.assertEqual(validate_project(self.path, artifacts=False).status, "passed")
        self.assertEqual(validate_project(self.path).status, "failed")

    def test_unsafe_and_aliased_output_bindings_are_rejected(self):
        for path in ("../escape.md", "/tmp/escape.md", "findings.json", "data/derived/areas.csv"):
            project = copy.deepcopy(self.project)
            project["outputs"]["findings"]["path"] = path
            self.assertTrue(declaration_errors(self.root, project), path)
        project = copy.deepcopy(self.project)
        project["outputs"]["alias"] = copy.deepcopy(project["outputs"]["findings"])
        self.assertTrue(declaration_errors(self.root, project))
        project["findings"]["output"] = ["findings"]
        self.assertTrue(declaration_errors(self.root, project))

    def test_writer_rejects_empty_claims_unknown_evidence_and_duplicate_ids(self):
        report = json.loads((self.root / "validation/latest-report.json").read_text())
        healthy = {"id": "answer", "statement": "One synthetic parcel qualifies.", "evidence": ["areas"]}
        for items in ([], [dict(healthy, evidence=["dashboard"])], [dict(healthy, statement=" ")],
                      [dict(healthy, evidence=["missing"])], [healthy, healthy], [None]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                write_findings(self.root, self.project, report=report, scope="all input", findings=items)

    def test_nested_markdown_links_resolve_and_unknown_checks_stay_unknown(self):
        report = json.loads((self.root / "validation/latest-report.json").read_text())
        report.update(status="warning")
        report["checks"].append({"id": "native_qgis", "status": "not_testable"})
        self.project["outputs"]["findings"]["path"] = "reports/analysis findings.md"
        path = write_findings(self.root, self.project, report=report, scope="all input", findings=[
            {"id": "answer", "statement": "One synthetic parcel qualifies.", "evidence": ["areas"]}])
        self.file = path
        metadata = self.metadata()
        self.assertEqual(metadata["validation"]["status"], "warning")
        self.assertEqual(metadata["validation"]["checks"][-1]["status"], "not_testable")
        self.assertIn("[areas](../data/derived/areas.csv)", path.read_text())

    def test_old_projects_have_no_findings_requirement(self):
        self.project.pop("findings")
        self.assertEqual(artifact_errors(self.root, self.project), [])

    def test_custom_validation_report_and_empty_result_findings(self):
        self.project["processing"]["steps"][1]["minimum_area_m2"] = 50000
        self.path.write_text(yaml.safe_dump(self.project, sort_keys=False))
        subprocess.run([sys.executable, str(self.root / "pipeline.py")], check=True, capture_output=True)
        self.project = yaml.safe_load(self.path.read_text())
        self.assertIn("No parcels qualify.", self.metadata()["findings"][0]["statement"])
        self.assertEqual(artifact_matches(self.root).status, "passed")
        report = json.loads((self.root / "validation/latest-report.json").read_text())
        (self.root / "validation/custom.json").write_text(json.dumps(report))
        self.project["runs"]["latest"]["validation_report"]["path"] = "validation/custom.json"
        write_findings(self.root, self.project, report=report, scope="all input",
                       findings=self.metadata()["findings"], validation_report="validation/custom.json")
        self.assertEqual(artifact_errors(self.root, self.project), [])
