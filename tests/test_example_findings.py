"""Worked-example findings describe exported results, including scenario limits."""

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import yaml

from tests.test_nyc_dashboard import pipeline_module

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def tartu_module(name):
    spec = importlib.util.spec_from_file_location("tartu_findings_" + name, EXAMPLES / "tartu-development" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    # Summaries and XML generation do not require a GIS runtime.
    import sys
    from types import SimpleNamespace
    with patch.dict(sys.modules, {"duckdb": SimpleNamespace(DuckDBPyConnection=object), "pyproj": SimpleNamespace()}):
        spec.loader.exec_module(module)
    return module


class ExampleFindingsTests(unittest.TestCase):
    def test_nyc_summaries_follow_exports_and_handle_an_empty_shortlist(self):
        pipeline = pipeline_module()
        manifest = yaml.safe_load((EXAMPLES / "nyc-private-mobility/project.yaml").read_text())
        row = {"zone_id": 1, "h3_cell": "cell-a", "borough": "Test borough", "final_score": 42.5,
               "trips_total": 31, "hub_distance_m": 1600, "fleet_present": 2}
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DERIVED", Path(directory)):
            for name in ("zone-metrics", "hub-candidates"):
                (Path(directory) / (name + ".geojson")).write_text(json.dumps({"features": [{"properties": row}]}))
            findings = pipeline.build_findings(manifest)
            self.assertIn("1 of 1", findings[0]["statement"])
            self.assertIn("cell-a", findings[1]["statement"])
            self.assertIn("42.50/100", findings[1]["statement"])
            self.assertIn("31 captured trip events", findings[2]["statement"])
            self.assertIn("Synthetic business records", findings[0]["limitations"][0])
            (Path(directory) / "hub-candidates.geojson").write_text('{"features": []}')
            empty = pipeline.build_findings(manifest)
            self.assertIn("0 of 1", empty[0]["statement"])
            self.assertNotIn("highest_scoring_cell", {item["id"] for item in empty})

    def test_tartu_counts_separate_planar_scenario_and_sampled_catchments(self):
        pipeline = tartu_module("pipeline")
        rows = [
            {"suitability_tier": pipeline.SUITABILITY_TIERS["candidates_tier1"],
             "dist_official_road_m": 500, "dist_scenario_road_m": 400,
             "isochrone_kg_baseline_min": 20, "isochrone_kg_effective_min": 20},
            {"suitability_tier": pipeline.SUITABILITY_TIERS["candidates_highway"],
             "dist_official_road_m": 2500, "dist_scenario_road_m": 2000,
             "isochrone_kg_baseline_min": 25, "isochrone_kg_effective_min": None},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DERIVED", Path(directory)):
            output = Path(directory) / "final-candidates.json"
            output.write_text(json.dumps({"features": [{"properties": row} for row in rows]}))
            findings = pipeline.build_findings()
            self.assertIn("2 parcels", findings[0]["statement"])
            self.assertIn("1 intersect both", findings[0]["statement"])
            self.assertIn("0 intersect one type", findings[0]["statement"])
            self.assertIn("1 of the 2", findings[1]["statement"])
            self.assertTrue(findings[2]["statement"].startswith("1 accepted parcels"))
            self.assertIn("not a claim that it has closed", findings[2]["limitations"][0])
            rows[1]["isochrone_kg_effective_min"] = 25
            rows[1]["dist_official_road_m"] = 2000
            output.write_text(json.dumps({"features": [{"properties": row} for row in rows]}))
            changed = pipeline.build_findings()
            self.assertTrue(changed[1]["statement"].startswith("0 of the 2"))
            self.assertTrue(changed[2]["statement"].startswith("0 accepted parcels"))

    def test_both_qgis_companions_expose_portable_findings_metadata(self):
        pipeline = pipeline_module()
        project = yaml.safe_load((EXAMPLES / "nyc-private-mobility/project.yaml").read_text())
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "ROOT", Path(directory)), patch.object(pipeline, "pyqgis_available", return_value=False):
            pipeline.write_qgis_project(project)
            nyc = ET.fromstring((Path(directory) / "project.qgs").read_text())
        tartu = tartu_module("qgis_delivery")
        project = yaml.safe_load((EXAMPLES / "tartu-development/project.yaml").read_text())
        document = ET.fromstring(tartu._qgs_document([], project, 3301))
        for root in (nyc, document):
            link = root.find("projectMetadata/links/link")
            self.assertEqual(link.get("url"), "findings.md")
            self.assertEqual(link.get("mimeType"), "text/markdown")
            self.assertIn("relative to this QGIS project", root.findtext("projectMetadata/abstract"))

    def test_both_dashboard_templates_link_findings_without_losing_provenance(self):
        for name in ("nyc-private-mobility", "tartu-development"):
            template = (EXAMPLES / name / "dashboard-template.html").read_text()
            self.assertIn('href="findings.md"', template)
            self.assertIn('role="tab"', template)
            self.assertIn("Provenance", template)
