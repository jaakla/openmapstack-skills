"""Warning-only static diagnostics and real coordinate-order guarantees."""
import unittest

from openmapstack.checks import project
from tests.evals.helpers import EVALS_DIR, make_workspace
from tests.test_evals import eval_runner


class StaticAxisOrderTests(unittest.TestCase):
    def check(self, body):
        workspace = make_workspace()
        (workspace / 'pipeline.py').write_text(body)
        return project.duckdb_axis_order_explicit(workspace)

    def test_setup_evidence_defers_and_obvious_omission_warns(self):
        for operation in ("SELECT ST_Transform(g, 'EPSG:4326', 'EPSG:3857')",
                          "COPY t TO 'out.gpkg' (FORMAT GDAL, DRIVER 'GPKG', SRS 'EPSG:4326')"):
            for setup in ("con.execute('SET geometry_always_xy = true')",
                          "con.execute('SET geometry_always_xy = false')",
                          "configure_spatial_axes(con)"):
                prefix = ('import duckdb\nfrom openmapstack.checks.spatial import configure_spatial_axes\n'
                          'con = duckdb.connect()\n')
                with self.subTest(operation=operation, setup=setup):
                    result = self.check(prefix + setup + '\ncon.execute(' + repr(operation) + ')')
                    self.assertEqual(result.status, 'not_testable')
                    self.assertIn('static analysis cannot prove axis order', result.detail)
                    self.assertIn('runtime coordinate-order assertion is the guarantee', result.detail)
                    self.assertEqual(self.check(prefix + 'con.execute(' + repr(operation) + ')').status, 'warning')

    def test_helper_connection_alias_is_only_evidence_not_proof(self):
        result = self.check("from openmapstack.checks.spatial import require_spatial as connect\nc = connect()\nc.sql(\"SELECT ST_Transform(g, 'a', 'b')\")")
        self.assertEqual(result.status, 'not_testable')

    def test_only_syntactic_setup_evidence_suppresses_omission_warning(self):
        base = 'import duckdb\nc = duckdb.connect()\nother = duckdb.connect()\n'
        op = 'c.execute("SELECT ST_Transform(g, a, b, always_xy := true)")\n'
        for setup in ('# SET geometry_always_xy = true\n', '"SET geometry_always_xy = true"\n'):
            self.assertEqual(self.check(base + setup + op).status, 'warning')
        # Presence is not a claim about connection identity or execution order.
        self.assertEqual(self.check(base + 'other.execute("SET geometry_always_xy = true")\n' + op).status,
                         'not_testable')
        self.assertEqual(self.check(base + op + 'c.execute("SET geometry_always_xy = true")').status,
                         'not_testable')

    def test_nested_queries_without_any_setup_evidence_warn(self):
        for query in ('print(c.execute("SELECT ST_Transform(g,a,b)").fetchone())',
                      'consume(value=c.sql("COPY t TO x (FORMAT GDAL)"))',
                      'def run(c):\n return c.execute("SELECT ST_Transform(g,a,b)")'):
            with self.subTest(query=query):
                self.assertEqual(self.check('import duckdb\n' + query).status, 'warning')

    def test_ambiguous_flow_never_passes(self):
        for source in (
            'import duckdb\nc = duckdb.connect()\nif enabled:\n c.execute("SET geometry_always_xy = true")\nc.execute("SELECT ST_Transform(g, a, b)")',
            'import duckdb\nc = duckdb.connect()\nc.execute(sql)',
            'def run(c):\n c.execute("SELECT ST_Transform(g, a, b)")',
            'import duckdb\nc = duckdb.connect()\nc.execute("-- SET geometry_always_xy = true\\nSELECT ST_Transform(g,a,b)")',
            'import duckdb\nc = duckdb.connect()\n# ST_Transform(g,a,b)',
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

    def test_nested_query_on_raw_connection_cannot_borrow_another_connections_setup(self):
        sql = ("SELECT ST_Transform(ST_Point(2755558.1473003766,8275444.877846606), "
               "'EPSG:3857', 'EPSG:4326')")
        prefix = ('import duckdb\nfrom openmapstack.checks.spatial import configure_spatial_axes\n'
                  'con = duckdb.connect()\nconfigure_spatial_axes(con)\n'
                  + 'con.execute(' + repr(sql) + ')\nraw = duckdb.connect()\n')
        query = 'raw.execute(' + repr(sql) + ').fetchone()'
        for wrapper in ('print({})', 'consume({})', 'consume(str({}))', 'consume(value={})'):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(self.check(prefix + wrapper.format(query)).status, 'not_testable')

    def test_unsupported_chained_side_effects_cannot_preserve_setup_proof(self):
        prefix = ('import duckdb\nfrom openmapstack.checks.spatial import configure_spatial_axes\n'
                  'c = duckdb.connect()\nconfigure_spatial_axes(c)\n')
        for call in ('c.execute("SELECT 1").execute("RESET geometry_always_xy")',
                     'c.execute("SELECT 1").unknown_callback()'):
            with self.subTest(call=call):
                source = prefix + call + '\nc.execute("SELECT ST_Transform(g,a,b)")'
                self.assertEqual(self.check(source).status, 'not_testable')

    def test_conflicting_imports_cannot_impersonate_trusted_setup(self):
        prefix = ('import duckdb\nfrom openmapstack.checks.spatial import configure_spatial_axes\n')
        body = ('c = duckdb.connect()\nconfigure_spatial_axes(c)\n'
                'c.execute("SELECT ST_Transform(g,a,b)")')
        for shadow in ('from unrelated import configure_spatial_axes\n',
                       'import unrelated as configure_spatial_axes\n',
                       'import unrelated as duckdb\n'):
            with self.subTest(shadow=shadow):
                self.assertEqual(self.check(prefix + shadow + body).status, 'not_testable')
                local = 'def run():\n' + ''.join(' ' + line + '\n' for line in (shadow + body).splitlines())
                self.assertEqual(self.check(prefix + local).status, 'not_testable')

    def test_unreadable_and_non_python_are_not_testable(self):
        workspace = make_workspace()
        for path in ('absent.py', 'pipeline.sql'):
            result = project.duckdb_axis_order_explicit(workspace, pipeline_path=path)
            self.assertEqual(result.status, 'not_testable')
            self.assertIn('runtime coordinate-order assertion is the guarantee', result.detail)
        self.assertEqual(self.check('invalid syntax!').status, 'not_testable')

    def test_all_adversarial_cases_never_pass(self):
        prefix = ('import duckdb\n'
                  'from openmapstack.checks.spatial import configure_spatial_axes, require_spatial\n')
        query = 'c.execute("SELECT ST_Transform(g,a,b)")\n'
        cases = {
            'nested call': 'c = require_spatial()\nprint(' + query.strip() + ')\n',
            'import shadowing': ('from unrelated import configure_spatial_axes\n'
                                 'c = duckdb.connect()\nconfigure_spatial_axes(c)\n' + query),
            'connection alias': ('c = require_spatial()\nraw = c\n'
                                 'raw.execute("RESET geometry_always_xy")\n' + query),
            'f-string SQL': 'c = require_spatial()\nc.execute(f"SELECT ST_Transform(g,{src},{dst})")\n',
            'locally shadowed helper': ('def run():\n'
                                        ' def configure_spatial_axes(c): pass\n'
                                        ' c = duckdb.connect()\n configure_spatial_axes(c)\n '
                                        + query),
            'aliased execute RESET': ('def reset(conn):\n execute = conn.execute\n'
                                      ' execute("RESET geometry_always_xy")\n'
                                      'c = require_spatial()\nreset(c)\n' + query),
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.assertNotEqual(self.check(prefix + body).status, 'passed')


class DuckDBAxisMutationTests(unittest.TestCase):
    def test_warning_diagnostic_does_not_grade_static_deferral_as_passed(self):
        result = eval_runner.run_case(EVALS_DIR / 'cases' / '970-duckdb-axis-setting-missing', 'fixture')
        self.assertEqual(result['status'], 'passed', result)  # Diagnostic expectations matched.
        self.assertEqual(result['score_type'], 'contract_ci')
        self.assertIsNone(result['mutation_analysis'])
        self.assertEqual([a['actual_status'] for a in result['assertions']], ['warning', 'not_testable'])
        capability = eval_runner.rollup_capability([result])
        self.assertEqual(capability['assertions_not_testable'], 1)
        self.assertFalse(capability['fully_exercised'])
        dimensions = eval_runner.rollup_dimensions([result])
        self.assertEqual(sum(d['passed'] for d in dimensions.values()), 1)
        self.assertEqual(sum(d.get('not_testable', 0) for d in dimensions.values()), 1)

    def test_wrong_setting_fails_runtime_coordinates_with_a_passing_healthy_twin(self):
        result = eval_runner.run_case(EVALS_DIR / 'cases' / '971-duckdb-axis-setting-wrong', 'fixture')
        self.assertEqual(result['status'], 'passed', result)
        self.assertTrue(result['mutation_analysis']['healthy_control_passed'])
        self.assertTrue(result['mutation_analysis']['isolated'])
        self.assertEqual(result['assertions'][0]['actual_status'], 'failed')
        self.assertEqual(result['mutation_analysis']['control']['assertions'][0]['actual_status'], 'passed')
