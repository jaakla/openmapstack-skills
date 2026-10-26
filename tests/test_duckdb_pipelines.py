"""Exercise the real pipeline connection setup with asymmetric coordinates."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

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


class AdditionalSpatialConnectionTests(unittest.TestCase):
    def connection_with_authority_axes(self):
        from openmapstack.checks.spatial import connect_spatial
        connection = connect_spatial()
        if connection is None:
            self.skipTest('prepared DuckDB Spatial required')
        self.addCleanup(connection.close)
        connection.execute('SET geometry_always_xy = false')
        return connection

    def assert_nyc_utm(self, connection):
        x, y = connection.execute("SELECT ST_X(g), ST_Y(g) FROM (SELECT ST_Transform("
                                  "ST_Point(-73.99,40.75), 'EPSG:4326', 'EPSG:32618') AS g)").fetchone()
        self.assertAlmostEqual(x, 585263, delta=2)
        self.assertAlmostEqual(y, 4511496, delta=2)

    def test_established_stack_loader_sets_connection_axes(self):
        spec = importlib.util.spec_from_file_location('axis_stack_analysis', ROOT / 'examples/established-stack/analysis.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection = self.connection_with_authority_axes()
        module.load_spatial(connection)
        self.assert_nyc_utm(connection)

    def test_dbt_profile_sets_spatial_connection_axes(self):
        profile = yaml.safe_load((ROOT / 'examples/established-stack/dbt/profiles.yml').read_text())
        settings = profile['spatial_example']['outputs']['local'].get('settings', {})
        self.assertIs(settings.get('geometry_always_xy'), True)
        connection = self.connection_with_authority_axes()
        connection.execute('SET geometry_always_xy = ' + str(settings['geometry_always_xy']).lower())
        self.assert_nyc_utm(connection)

    def test_motherduck_provisioner_sets_spatial_axes_before_fixture_sql(self):
        spec = importlib.util.spec_from_file_location('axis_nyc_provision', ROOT / 'examples/nyc-private-mobility/provision.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection = self.connection_with_authority_axes()
        commands = []
        class ProvisionSession:
            def execute(self, sql):
                commands.append(sql)
                if sql == 'LOAD spatial' or sql.startswith('SET geometry_always_xy'):
                    return connection.execute(sql)
                return self
            def close(self):
                commands.append('CLOSE')
        with patch.object(module, '_motherduck_connect', return_value=ProvisionSession()):
            module.provision_motherduck('fake-test-token', 'test_database')
        self.assert_nyc_utm(connection)
        self.assertLess(commands.index('LOAD spatial'), commands.index('SET geometry_always_xy = true'))
        self.assertEqual(commands[-1], 'CLOSE')
