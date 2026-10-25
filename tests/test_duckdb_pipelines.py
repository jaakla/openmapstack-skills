"""Exercise the real pipeline connection setup with asymmetric coordinates."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from openmapstack.checks import geodata

ROOT = Path(__file__).resolve().parents[1]
TARTU_DEPENDENCIES = unittest.skipUnless(
    importlib.util.find_spec('pyproj'),
    'Tartu example requires optional pyproj; install examples/tartu-development/requirements.txt',
)


class PipelineAxisOrderTests(unittest.TestCase):
    def test_all_pipeline_connections_transform_and_export_the_known_point(self):
        pipelines = ('evals/fixtures/reference_pipeline/gen.py',
                     'examples/nyc-private-mobility/pipeline.py',
                     'templates/pipeline.py')
        for relative in pipelines:
            with self.subTest(pipeline=relative):
                self.check_pipeline(relative)

    @TARTU_DEPENDENCIES
    def test_tartu_connection_transforms_and_exports_the_known_point(self):
        self.check_pipeline('examples/tartu-development/pipeline.py')

    def check_pipeline(self, relative):
        with tempfile.TemporaryDirectory() as folder:
            spec = importlib.util.spec_from_file_location('axis_pipeline', ROOT / relative)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # NYC's main calls the shared factory directly. The others
            # expose their factory so this executes their actual setup.
            connection = (module.connect_spatial() if 'nyc-' in relative else module._connect_spatial())
            self.assertIsNotNone(connection)
            try:
                has_setting = connection.execute("SELECT name FROM duckdb_settings() WHERE name='geometry_always_xy'").fetchone()
                if has_setting:
                    self.assertEqual(connection.execute("SELECT current_setting('geometry_always_xy')").fetchone(), (True,))
                query = ("SELECT ST_Transform(ST_Point(2755558.1473003766, 8275444.877846606), "
                         "'EPSG:3857', 'EPSG:4326', always_xy := true) AS geometry")
                point = json.loads(connection.execute('SELECT ST_AsGeoJSON(geometry) FROM (' + query + ')').fetchone()[0])
                workspace = Path(folder)
                (workspace / 'point.json').write_text(json.dumps(point))
                result = geodata.coordinate_pair_equals(workspace, path='point.json', field='coordinates', equals=[24.7536, 59.4370])
                self.assertEqual(result.status, 'passed', result.detail)
                path = (workspace / 'point.gpkg').as_posix().replace("'", "''")
                connection.execute(f"COPY ({query}) TO '{path}' (FORMAT GDAL, DRIVER 'GPKG', SRS 'EPSG:4326')")
                point = json.loads(connection.execute(f"SELECT ST_AsGeoJSON(geom) FROM ST_Read('{path}')").fetchone()[0])
                (workspace / 'point.json').write_text(json.dumps(point))
                self.assertEqual(geodata.coordinate_pair_equals(workspace, path='point.json', field='coordinates', equals=[24.7536, 59.4370]).status, 'passed')
            finally:
                connection.close()

    @TARTU_DEPENDENCIES
    def test_tartu_reads_feature_collection_without_geometry_auto_inference(self):
        spec = importlib.util.spec_from_file_location('tartu_roads', ROOT / 'examples/tartu-development/pipeline.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection = module._connect_spatial()
        self.addCleanup(connection.close)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'roads.geojson'
            path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[659000, 6473000], [659100, 6473100]]},
                 'properties': {'nimetus': 'Known road', 'tyyp_tekst': 'Põhimaantee'}}]}))
            module.load_roads(connection, path)
        self.assertEqual(connection.execute('SELECT name, road_class, ST_AsText(geometry) FROM official_roads').fetchall(),
                         [('Known road', 'Põhimaantee', 'LINESTRING (659000 6473000, 659100 6473100)')])
