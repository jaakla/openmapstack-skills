"""City delivery samples replay checked-in public snapshots without GIS services."""
from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

from openmapstack.delivery import declaration_errors
from openmapstack.integration import binding_errors
from openmapstack.validation import validate_project
from openmapstack.checks import delivery as delivery_checks, integration as integration_checks
from scripts.build_project_pages import build

HERE = Path(__file__).resolve().parents[1] / "examples/observable-cities"


def module(name):
    spec = importlib.util.spec_from_file_location("observable_city_" + name, HERE / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


create = module("create").create
pipeline = module("pipeline")


class ObservableCitiesTests(unittest.TestCase):
    def test_city_profiles_export_the_original_rows_and_provenance(self):
        for city, expected in (("tartu", 518), ("nyc", 83)):
            with self.subTest(city=city), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / city
                project_file = create(root, city)
                project = yaml.safe_load(project_file.read_text())
                self.assertEqual(project["delivery"]["targets"][0]["kind"], "observable")
                self.assertEqual(declaration_errors(project, root), [])
                self.assertEqual(binding_errors(root, project), [])
                result = validate_project(project_file, artifacts=False)
                self.assertTrue(result.ok(), [c.to_dict() for c in result.checks if c.status == "failed"])
                info = pipeline.export(root, project)
                features = json.loads((root / "data/derived/features.geojson").read_text())["features"]
                self.assertEqual(len(features), expected)
                with (root / "data/derived/metrics.csv").open() as stream:
                    metrics = list(csv.DictReader(stream))
                self.assertEqual(len(metrics), len(features))
                self.assertEqual(len({r["id"] for r in metrics}), expected)
                for feature, row in zip(features, metrics):
                    p = feature["properties"]
                    self.assertEqual(row["id"], p["cadastral_id" if city == "tartu" else "h3_cell"])
                    value = p["area_m2" if city == "tartu" else "final_score"]
                    self.assertEqual(row["value"], "" if value is None else str(value))
                notes = "\n".join(info["notes"])
                for warning in project.get("warnings", []):
                    self.assertIn(warning["statement"], notes)
                upstream = yaml.safe_load((root / "data/source/project.yaml").read_text())
                for source in upstream["sources"].values():
                    for text in (source["provider"], source["license"]["name"], str(source["version"]["identifier"])):
                        self.assertIn(text, notes)
                before = (root / "data/derived/features.geojson").read_bytes()
                pipeline.export(root, project)
                self.assertEqual((root / "data/derived/features.geojson").read_bytes(), before)

    def test_changed_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "nyc"
            project = yaml.safe_load(create(root, "nyc").read_text())
            with (root / "data/source/dashboard.html").open("a") as stream:
                stream.write("changed")
            with self.assertRaisesRegex(ValueError, "pinned city snapshot changed"):
                pipeline.export(root, project)

    def test_run_mismatch_and_missing_payload_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "tartu"
            project = yaml.safe_load(create(root, "tartu").read_text())
            project["sample"]["upstream_run"] = "different-run"
            with self.assertRaisesRegex(ValueError, "run IDs disagree"):
                pipeline.export(root, project)
        with self.assertRaisesRegex(ValueError, "lacks JSON constant"):
            pipeline.constant("const VIEW = unsafeJavaScript();", "CANDIDATES")

    def test_creation_preserves_existing_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "notes.txt"
            existing.write_text("user work")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                create(root, "nyc")
            self.assertEqual(existing.read_text(), "user work")
        with self.assertRaises(ValueError):
            create(HERE / "generated", "tartu")

    @unittest.skipUnless(shutil.which("node"), "render geometry check needs Node")
    def test_plot_winding_handles_holes_and_multiparts_without_mutating_exports(self):
        script = """
import {forPlot, filterFeatures} from SOURCE;
import assert from 'node:assert/strict';
const outer = [[0,0],[2,0],[2,2],[0,2],[0,0]];
const hole = [[0.5,0.5],[0.5,1.5],[1.5,1.5],[1.5,0.5],[0.5,0.5]];
const input = {type:'FeatureCollection', features:[
  {geometry:{type:'Polygon',coordinates:[outer,hole]},properties:{eligible:true,borough:'Queens'}},
  {geometry:{type:'MultiPolygon',coordinates:[[outer,hole]]},properties:{eligible:false,borough:'Manhattan'}}
]};
const before = JSON.stringify(input);
const output = forPlot(input);
const area = ring => ring.slice(1).reduce((sum,b,i) => sum + ring[i][0]*b[1] - b[0]*ring[i][1],0);
assert.ok(area(output.features[0].geometry.coordinates[0]) < 0);
assert.ok(area(output.features[0].geometry.coordinates[1]) > 0);
assert.ok(area(output.features[1].geometry.coordinates[0][0]) < 0);
assert.equal(JSON.stringify(input),before);
assert.deepEqual(forPlot(output),output);
assert.equal(filterFeatures('nyc',output.features,{category:'Queens',eligibility:'eligible'}).length,1);
assert.equal(filterFeatures('nyc',output.features,{category:'Queens',eligibility:'ineligible'}).length,0);
""".replace("SOURCE", json.dumps((HERE / "observable/src/view.js").as_uri()))
        subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True)


@unittest.skipUnless(os.environ.get("OMS_OBSERVABLE_CITY_PROJECTS"),
                     "real Framework/browser QA needs built projects via OMS_OBSERVABLE_CITY_PROJECTS")
class ObservableCityBrowserTests(unittest.TestCase):
    def test_contracts_and_interactions_under_pages_subpath(self):
        from playwright.sync_api import sync_playwright
        projects = Path(os.environ["OMS_OBSERVABLE_CITY_PROJECTS"]).resolve()
        with tempfile.TemporaryDirectory() as temporary, sync_playwright() as pw:
            root = Path(temporary)
            (root / "index.html").write_text("test server")
            site = root / "openmapstack-skills"
            build(site, observable_projects=projects)
            browser = pw.chromium.launch()
            try:
                with delivery_checks._serve_bundle(root / "index.html") as server:
                    base = server.rsplit("/", 1)[0] + "/openmapstack-skills/"
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    problems = []
                    page.on("pageerror", lambda error: problems.append(str(error)))
                    page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
                    page.on("response", lambda response: problems.append(str(response.status) + " " + response.url)
                            if response.status >= 400 else None)
                    page.goto(base, wait_until="networkidle")
                    self.assertEqual(page.get_by_role("link", name="Observable Framework").count(), 2)
                    for city, count, title in (("tartu", 518, "Development parcels"), ("nyc", 83, "Mobility hub")):
                        with self.subTest(city=city):
                            project_root = projects / city
                            validation = validate_project(project_root / "project.yaml")
                            self.assertEqual(validation.status, "passed", validation.to_dict())
                            self.assertEqual(delivery_checks.evidence_matches(project_root, "observable").status, "passed")
                            self.assertEqual(integration_checks.evidence_matches(project_root).status, "passed")
                            page.goto(base + f"demos/{city}-observable/", wait_until="networkidle")
                            self.assertIn(title, page.title())
                            self.assertIn(f"{count} of {count} rows", page.locator("#snapshot-status").inner_text())
                            self.assertEqual(page.locator("svg.map").count(), 1)
                            self.assertEqual(page.locator(".observablehq--error").count(), 0)
                            self.assertTrue(page.locator("[data-openmapstack-provenance]").is_visible())
                            label = "Suitability tier" if city == "tartu" else "Borough"
                            control = page.get_by_label(label)
                            value = control.locator("option").nth(1).get_attribute("value")
                            control.select_option(value)
                            page.wait_for_function("document.querySelector('#snapshot-status').textContent.includes('Exploratory subset')")
                            self.assertLess(page.locator("#snapshot-table tbody tr").count(), count)
                            if city == "nyc":
                                page.get_by_label("Eligibility").select_option("eligible")
                            page.get_by_role("button", name="Reset to snapshot").click()
                            page.wait_for_function("document.querySelector('#snapshot-status').textContent.startsWith('Accepted snapshot')")
                            self.assertEqual(page.locator("#snapshot-table tbody tr").count(), count)
                            credits = page.locator("[data-openmapstack-credits]")
                            self.assertEqual(credits.count(), 1)
                            self.assertTrue(credits.is_visible())
                            self.assertIn("OpenMapStack example maintainers", credits.inner_text())
                            self.assertEqual(credits.locator('[data-oms-credit="author"]').get_attribute("href"),
                                             "mailto:examples@example.invalid")
                            with page.expect_download() as pending:
                                page.get_by_role("link", name="metrics CSV", exact=True).click()
                            self.assertEqual(Path(pending.value.path()).read_bytes(),
                                             (project_root / "data/derived/metrics.csv").read_bytes())
                            page.evaluate("window.scrollTo(0, 0)")
                            page.screenshot(path=f"/tmp/oms-{city}-desktop.png")
                            page.set_viewport_size({"width": 390, "height": 844})
                            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                            control.select_option(value)
                            page.wait_for_function("document.querySelector('#snapshot-status').textContent.includes('Exploratory subset')")
                            page.evaluate("window.scrollTo(0, 0)")
                            page.screenshot(path=f"/tmp/oms-{city}-mobile.png")
                            page.set_viewport_size({"width": 1440, "height": 1100})
                    self.assertEqual(problems, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
