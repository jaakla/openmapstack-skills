"""Credit checks inspect rendered fields, not a renderer's receipt."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import yaml

from openmapstack import credits
from openmapstack.checks.credits import declaration_valid, rendered_matches
from openmapstack.schema import project_schema_errors
from openmapstack.validation import validate_project
from openmapstack.verify import verify_project
from tests.test_delivery import example


class CreditsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = example.create(self.root, ["dashboard", "qgis"])
        subprocess.run([sys.executable, str(self.root / "pipeline.py")], check=True, capture_output=True)
        self.project = yaml.safe_load(self.path.read_text())
        self.html = self.root / self.project["outputs"]["dashboard"]["path"]
        self.qgz = self.root / self.project["outputs"]["qgis"]["path"]

    def save(self):
        self.path.write_text(yaml.safe_dump(self.project, sort_keys=False))

    def edit_qgis(self, change):
        with zipfile.ZipFile(self.qgz) as archive:
            tree = ET.fromstring(archive.read("project.qgs"))
        change(tree)
        with zipfile.ZipFile(self.qgz, "w") as archive:
            archive.writestr("project.qgs", ET.tostring(tree))

    def test_healthy_html_qgis_and_public_validation_plan(self):
        self.assertEqual(declaration_valid(self.root).status, "passed")
        self.assertEqual(rendered_matches(self.root).status, "passed")
        self.assertEqual(validate_project(self.path).status, "passed")
        planned = {c.name: c.result for c in verify_project(self.path).checks}
        self.assertEqual(planned["credits.rendered_matches"].status, "passed")
        body = self.html.read_text()
        self.assertIn("Generated with AI using the free", body)
        self.assertIn(credits.credit_payload(self.project)["analysis_at"], body)

        # An additional declared report page also needs credits, even when the
        # delivery target binds the entry dashboard separately.
        self.project["outputs"]["report"] = {"path": "report.html", "kind": "document", "format": "HTML", "generated_by": "render"}
        self.project["views"] = [{"id": "report", "output": "report", "archetype": "report"}]
        self.save()
        report = self.root / "report.html"
        report.write_text(body)
        self.assertEqual(rendered_matches(self.root).status, "passed")
        report.write_text("<html><body>Report without credits</body></html>")
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_missing_both_is_explicit_legacy_warning_but_partial_is_failed(self):
        self.project["project"].pop("author")
        self.save()
        self.assertEqual(declaration_valid(self.root).data["code"], "credits_declaration_invalid")
        self.project["project"].pop("generated_with")
        self.save()
        result = rendered_matches(self.root)
        self.assertEqual((result.status, result.data["code"]), ("warning", "credits_legacy_missing"))
        checks = {c.id: c for c in validate_project(self.path, artifacts=False).checks}
        self.assertEqual(checks["credits.declaration"].status, "warning")
        self.assertTrue(validate_project(self.path, artifacts=False).ok())

    def test_metadata_rejects_placeholders_bad_email_and_unsafe_urls(self):
        original = copy.deepcopy(self.project)
        mutations = [
            ("author", "name", "TODO-author-name"), ("author", "email", "TODO-author-email"),
            ("author", "url", "javascript:alert(1)"), ("generated_with", "url", "https://"),
            ("generated_with", "tool", "Some agent"), ("author", "url", "https://user:secret@host.invalid"),
            ("author", "url", "https://example.invalid:bad"),
            ("generated_with", "url", "https://example.invalid:99999"),
        ]
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                self.project = copy.deepcopy(original)
                self.project["project"][section][key] = value
                self.save()
                self.assertEqual(declaration_valid(self.root).status, "failed")
        self.project["project"]["author"] = "not an object"
        self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")
        self.assertTrue(project_schema_errors(self.project))

    def test_html_missing_hidden_stale_and_broken_links_fail_independently(self):
        original = self.html.read_text()
        timestamp = credits.credit_payload(self.project)["analysis_at"]
        changes = [
            lambda s: s.replace("data-openmapstack-credits", "data-removed-credits"),
            lambda s: s.replace("data-openmapstack-credits", "data-openmapstack-credits hidden"),
            lambda s: s.replace(timestamp, "2000-01-01T00:00:00+00:00"),
            lambda s: s.replace('href="mailto:examples@example.invalid"', 'href="mailto:wrong@example.invalid"'),
            lambda s: s.replace('href="https://jaakla.github.io/openmapstack-skills/"', 'href="javascript:alert(1)"'),
            lambda s: s.replace('data-oms-credit="toolkit"', 'data-oms-credit="other"'),
        ]
        for change in changes:
            self.html.write_text(change(original))
            result = rendered_matches(self.root)
            self.assertEqual((result.status, result.data["code"]), ("failed", "credits_rendered_mismatch"))
        self.html.write_text(original)
        # Correct machine datetime cannot certify stale visible time text.
        self.html.write_text(original.replace('>' + timestamp + '</time>', '>2000-01-01T00:00:00+00:00</time>'))
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_qgis_missing_stale_and_broken_links_fail(self):
        original = self.qgz.read_bytes()
        changes = [
            lambda tree: tree.remove(tree.find("projectMetadata")),
            lambda tree: setattr(tree.find("projectMetadata/author"), "text", "wrong author"),
            lambda tree: setattr(tree.find("projectMetadata/abstract"), "text", "Analysis made: 2000-01-01T00:00:00+00:00"),
            lambda tree: tree.find('projectMetadata/links/link[@name="Author email"]').set("url", "mailto:wrong@example.invalid"),
        ]
        for change in changes:
            self.qgz.write_bytes(original)
            self.edit_qgis(change)
            self.assertEqual(rendered_matches(self.root).status, "failed")
        self.qgz.write_bytes(b"broken zip")
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_author_and_clock_changes_require_new_rendered_credits(self):
        # A shorter name must not pass by matching a substring of stale text.
        self.project["project"]["author"]["name"] = "OpenMapStack"
        self.save()
        self.assertEqual(rendered_matches(self.root).status, "failed")
        self.project["project"]["author"]["name"] = "A different analyst"
        self.save()
        self.assertEqual(rendered_matches(self.root).status, "failed")
        self.project["runs"]["latest"]["completed_at"] = "2026-10-16T17:00:00"
        self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")
        self.project["runs"]["latest"].pop("completed_at")
        self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")

    def test_labeled_prerun_fallback_optional_site_and_escaping(self):
        self.project["runs"]["latest"] = None
        self.project["project"]["author"].update(name='<script>alert("author")</script>', url="https://example.invalid/author?a=1&b=2")
        self.project["project"]["updated_at"] = "2026-10-16T20:30:00+03:00"
        self.save()
        values = credits.credit_payload(self.project)
        body = credits.html_credits(values)
        self.assertNotIn('<script>', body)
        self.assertIn('no canonical run yet', body)
        self.html.write_text(body)
        credits.write_qgis_credits(self.qgz, values)
        self.assertEqual(rendered_matches(self.root).status, "passed")
        self.html.write_text(body.replace('href="https://example.invalid/author?a=1&amp;b=2"', 'href="https://wrong.invalid"'))
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_no_views_and_legacy_known_paths_missing_files_and_malformed_inputs(self):
        self.project.pop("delivery")
        self.save()
        self.assertEqual(rendered_matches(self.root).status, "passed")
        self.html.unlink()
        self.assertEqual(rendered_matches(self.root).status, "failed")
        self.project["outputs"] = {}; self.qgz.unlink(); self.project["presentation"].pop("dashboard", None)
        self.save()
        result = rendered_matches(self.root)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.data["surfaces"], [])
        self.project["project"] = None; self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")
        self.path.unlink()
        self.assertEqual(rendered_matches(self.root).data["code"], "manifest_missing")

    def test_qgis_updater_keeps_findings_attachments_and_zip_dates(self):
        values = credits.credit_payload(self.project)
        with zipfile.ZipFile(self.qgz, "a") as archive:
            archive.writestr("styles.db", b"synthetic attachment")
        credits.write_qgis_credits(self.qgz, values)
        credits.write_qgis_credits(self.qgz, values)
        with zipfile.ZipFile(self.qgz) as archive:
            self.assertEqual(archive.read("styles.db"), b"synthetic attachment")
            tree = ET.fromstring(archive.read("project.qgs"))
        self.assertEqual(len(tree.findall('projectMetadata/links/link[@name="Author email"]')), 1)
        self.assertIsNotNone(tree.find('projectMetadata/links/link[@name="Findings"]'))
        qgs = self.root / "companion.qgs"
        qgs.write_bytes(ET.tostring(tree))
        credits.write_qgis_credits(qgs, values)
        self.assertIn(values["analysis_at"], qgs.read_text())
