"""Static setup evidence and real asymmetric-point mutation regressions."""
from pathlib import Path
import unittest

from openmapstack.checks import project
from tests.evals.helpers import EVALS_DIR, make_workspace
from tests.test_evals import eval_runner


class StaticAxisOrderTests(unittest.TestCase):
    def check(self, body):
        workspace = make_workspace()
        (workspace / 'pipeline.py').write_text(body)
        return project.duckdb_axis_order_explicit(workspace)

    def test_explicit_setting_precedes_each_sensitive_operation(self):
        for operation in ("SELECT ST_Transform(g, 'EPSG:4326', 'EPSG:3857')",
                          "COPY t TO 'out.gpkg' (FORMAT GDAL, DRIVER 'GPKG', SRS 'EPSG:4326')"):
            for setup in ("con.execute('SET geometry_always_xy = true')",
                          "con.execute('SET geometry_always_xy = false')",
                          "configure_spatial_axes(con)"):
                prefix = ('import duckdb\nfrom openmapstack.checks.spatial import configure_spatial_axes\n'
                          'con = duckdb.connect()\n')
                with self.subTest(operation=operation, setup=setup):
                    self.assertEqual(self.check(prefix + setup + '\ncon.execute(' + repr(operation) + ')').status, 'passed')
                    self.assertEqual(self.check(prefix + 'con.execute(' + repr(operation) + ')').status, 'warning')

    def test_helper_connection_alias_is_recognized(self):
        result = self.check("from openmapstack.checks.spatial import require_spatial as connect\nc = connect()\nc.sql(\"SELECT ST_Transform(g, 'a', 'b')\")")
        self.assertEqual(result.status, 'passed')

    def test_other_connection_late_setting_comments_and_per_call_axes_do_not_hide_missing_setup(self):
        base = 'import duckdb\nc = duckdb.connect()\nother = duckdb.connect()\n'
        op = 'c.execute("SELECT ST_Transform(g, a, b, always_xy := true)")\n'
        for setup in ('# SET geometry_always_xy = true\n', '"SET geometry_always_xy = true"\n',
                      'other.execute("SET geometry_always_xy = true")\n'):
            self.assertEqual(self.check(base + setup + op).status, 'warning')
        self.assertEqual(self.check(base + op + 'c.execute("SET geometry_always_xy = true")').status, 'warning')

    def test_ambiguous_flow_never_passes(self):
        for source in (
            'import duckdb\nc = duckdb.connect()\nif enabled:\n c.execute("SET geometry_always_xy = true")\nc.execute("SELECT ST_Transform(g, a, b)")',
            'import duckdb\nc = duckdb.connect()\nc.execute(sql)',
            'def run(c):\n c.execute("SELECT ST_Transform(g, a, b)")',
            'import duckdb\nc = duckdb.connect()\nc.execute("-- SET geometry_always_xy = true\\nSELECT ST_Transform(g,a,b)")',
            'import duckdb\nc = duckdb.connect()\n# ST_Transform(g,a,b)',
            'import duckdb\ndef run(c):\n return c.execute("SELECT ST_Transform(g,a,b)")',
        ):
            with self.subTest(source=source):
                self.assertEqual(self.check(source).status, 'not_testable')

    def test_sql_string_cannot_impersonate_a_setting(self):
        source = "import duckdb\nc = duckdb.connect()\nc.execute(\"SELECT '; SET geometry_always_xy=true;'; SELECT ST_Transform(g,a,b)\")"
        self.assertEqual(self.check(source).status, 'not_testable')

    def test_shadowed_setup_is_not_proof(self):
        source = ('from openmapstack.checks.spatial import configure_spatial_axes\n'
                  'import duckdb\nconfigure_spatial_axes = lambda c: None\n'
                  'c = duckdb.connect()\nconfigure_spatial_axes(c)\n'
                  'c.execute("SELECT ST_Transform(g,a,b)")')
        self.assertNotEqual(self.check(source).status, 'passed')

    def test_unreadable_and_non_python_are_not_testable(self):
        workspace = make_workspace()
        for path in ('absent.py', 'pipeline.sql'):
            self.assertEqual(project.duckdb_axis_order_explicit(workspace, pipeline_path=path).status, 'not_testable')
        self.assertEqual(self.check('invalid syntax!').status, 'not_testable')


class DuckDBAxisMutationTests(unittest.TestCase):
    def test_missing_setup_warns_and_wrong_setting_fails_coordinates_with_healthy_twins(self):
        for case in ('970-duckdb-axis-setting-missing', '971-duckdb-axis-setting-wrong'):
            with self.subTest(case=case):
                result = eval_runner.run_case(EVALS_DIR / 'cases' / case, 'fixture')
                self.assertEqual(result['status'], 'passed', result)
                self.assertTrue(result['mutation_analysis']['healthy_control_passed'])
                self.assertTrue(result['mutation_analysis']['isolated'])
