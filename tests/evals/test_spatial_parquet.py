"""Real Parquet regressions from native acceptance; no agent or network required."""
from __future__ import annotations

import unittest

from openmapstack.checks import geodata, validation
from .helpers import make_workspace, write_json


class SpatialParquetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = make_workspace()
        self.con = geodata._connect()
        if self.con is None:
            self.skipTest("prepared DuckDB Spatial required")
        self.addCleanup(self.con.close)

    def write_parquet(self, *, column="geometry", metadata=True, empty=False, invalid=False,
                      null=False):
        path = self.workspace / "shapes.parquet"
        quoted = '"' + column.replace('"', '""') + '"'
        wkt = "POLYGON((0 0,2 2,2 0,0 2,0 0))" if invalid else "POINT(650000 6475000)"
        value = "NULL" if null else f"ST_GeomFromText('{wkt}')"
        # Use the real writer's PROJJSON metadata, then write standard WKB with it.
        self.con.execute(
            f"COPY (SELECT ST_GeomFromText('{wkt}')::GEOMETRY('EPSG:3301') AS {quoted}) "
            f"TO '{path}' (FORMAT PARQUET)"
        )
        kv = self.con.execute("SELECT value FROM parquet_kv_metadata(?) WHERE key = 'geo'",
                              [str(path)]).fetchone()[0]
        geo = bytes(kv).decode().replace("'", "''")
        option = f", KV_METADATA {{geo: '{geo}'}}" if metadata else ""
        where = " WHERE FALSE" if empty else ""
        self.con.execute(
            f"COPY (SELECT ST_AsWKB({value}) AS {quoted}{where}) "
            f"TO '{path}' (FORMAT PARQUET{option})"
        )
        return path.name

    def test_wkb_geoparquet_custom_column_and_actual_crs(self) -> None:
        path = self.write_parquet(column='survey"shape')
        valid = geodata.geometry_all_valid(self.workspace, path)
        self.assertEqual(valid.status, "passed", valid.detail)
        result = geodata.dataset_crs_is(self.workspace, path, "EPSG:3301")
        self.assertEqual(result.status, "passed", result.detail)
        wrong = geodata.dataset_crs_is(self.workspace, path, "EPSG:4326")
        self.assertEqual(wrong.data.get("code"), "dataset_crs_mismatch")

    def test_bare_wkb_is_valid_geometry_but_does_not_invent_crs(self) -> None:
        path = self.write_parquet(metadata=False)
        valid = geodata.geometry_all_valid(self.workspace, path)
        self.assertEqual(valid.status, "passed", valid.detail)
        result = geodata.dataset_crs_is(self.workspace, path, "EPSG:3301")
        self.assertEqual(result.status, "failed", result.detail)
        self.assertEqual(result.data.get("code"), "dataset_crs_missing")

    def test_empty_geoparquet_preserves_crs(self) -> None:
        path = self.write_parquet(column="footprint", empty=True)
        result = geodata.dataset_crs_is(self.workspace, path, "EPSG:3301")
        self.assertEqual(result.status, "passed", result.detail)
        self.assertEqual(geodata.row_count(self.workspace, path, equals=0).status, "passed")

    def test_invalid_and_null_geometry_are_not_valid(self) -> None:
        for metadata in [True, False]:
            for kwargs in [{"invalid": True}, {"null": True}]:
                with self.subTest(metadata=metadata, **kwargs):
                    path = self.write_parquet(metadata=metadata, **kwargs)
                    result = geodata.geometry_all_valid(self.workspace, path)
                    self.assertEqual(result.status, "failed", result.detail)
                    self.assertEqual(result.data.get("code"), "invalid_geometry")

    def test_evidence_recomputes_real_column_and_rejects_laundered_count(self) -> None:
        for metadata in [True, False]:
            path = self.write_parquet(metadata=metadata, invalid=True)
            for declared, status in [(1, "passed"), (0, "failed")]:
                write_json(self.workspace, "validation/latest-report.json", {
                    "checks": [{"id": "validity", "invalid_count": declared}]
                })
                result = validation.report_evidence_recomputes(self.workspace, evidence=[{
                    "check_id": "validity", "evidence_field": "invalid_count",
                    "metric": "invalid_geometry_count", "path": path,
                }])
                self.assertEqual(result.status, status, result.detail)
                if status == "failed":
                    self.assertEqual(result.data.get("code"), "evidence_mismatch")

    def test_explicit_geometry_field_cannot_fall_back_to_another(self) -> None:
        path = self.write_parquet()
        result = geodata.dataset_crs_is(self.workspace, path, "EPSG:3301", geometry_field="absent")
        self.assertEqual(result.data.get("code"), "geometry_column_missing")
