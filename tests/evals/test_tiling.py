"""Tiling plan oracle, fixture mutations, and live-grader wiring without model calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openmapstack import api
from openmapstack.checks.tiling import command_matches
from tests.test_evals import AgentRunResult, eval_runner

CASES = Path(__file__).resolve().parents[2] / 'evals/cases'
EXPECTED = ['tylertoo', 'tiles', 'cells.parquet', 'cells.pmtiles',
            '--min-zoom', '4', '--max-zoom', '8', '--layer-name', 'cells', '--verbatim']


class TilingCheckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'plan.json'

    def check(self, command):
        self.path.write_text(json.dumps({'coverage': command}))
        return self.result()

    def result(self):
        return command_matches(self.root, path='plan.json', field='coverage', expected=EXPECTED)

    def test_order_and_equals_syntax_are_equivalent(self):
        self.assertEqual(self.check(EXPECTED).status, 'passed')
        self.assertEqual(self.check(['tylertoo', '--verbatim', '--max-zoom=8', 'tiles',
            'cells.parquet', 'cells.pmtiles', '--layer-name=cells', '--min-zoom=4']).status, 'passed')

    def test_missing_safeguard_wrong_input_and_zoom_fail(self):
        for command in (EXPECTED[:-1], [v.replace('cells.parquet', 'cells.geojson') for v in EXPECTED],
                        [v.replace('8', '9') for v in EXPECTED]):
            self.assertEqual(self.check(command).data['code'], 'tiler_command_mismatch')

    def test_invalid_commands_and_override_attempts_fail(self):
        for command in (None, {}, [], 'tylertoo', [True], ['bash', '-c', 'tylertoo'],
                        EXPECTED + ['--max-tile-size', '500K'],
                        EXPECTED + ['--max-zoom', '8'], EXPECTED + ['--min-zoom'],
                        EXPECTED + ['--unknown'], EXPECTED[:-1] + ['--verbatim=false'],
                        ['tylertoo', '--max-zoom='], ['tylertoo', '--max-zoom', '--verbatim']):
            with self.subTest(command=command):
                self.assertEqual(self.check(command).data['code'], 'tiler_command_invalid')

    def test_filter_json_compares_structurally(self):
        command = ['tippecanoe', '--feature-filter', '{"*": [">", "population", 10000]}', 'cities.geojson']
        self.path.write_text(json.dumps({'existing': ['tippecanoe', '--feature-filter={"*":[">","population",10000]}', 'cities.geojson']}))
        self.assertEqual(command_matches(self.root, path='plan.json', field='existing', expected=command).status, 'passed')

    def test_missing_malformed_and_unreadable_plan(self):
        self.assertEqual(self.result().data['code'], 'file_missing')
        self.path.write_text('{')
        self.assertEqual(self.result().data['code'], 'json_invalid')
        self.path.write_text('[]')
        self.assertEqual(self.result().data['code'], 'tiler_command_invalid')
        with patch.object(Path, 'read_text', side_effect=OSError('denied')):
            self.assertEqual(self.result().status, 'not_testable')
        with self.assertRaises(ValueError):
            command_matches(self.root, path='plan.json', field='coverage', expected=[])

    def test_public_api_requires_independent_oracle(self):
        self.assertFalse(api.describe_check('tiling.command_matches').oracle_free)


class TilingCaseTests(unittest.TestCase):
    def test_fixtures_and_healthy_control_mutations(self):
        for name in ('026-tiler-selection', '947-tiler-wrong-tool', '948-tiler-thinning',
                     '949-tiler-replace-existing'):
            with self.subTest(case=name):
                result = eval_runner.run_case(CASES / name, 'fixture')
                self.assertEqual(result['status'], 'passed', result)
                if name.startswith('9'):
                    target = next(a for a in result['assertions'] if a['mutation_role'] == 'target')
                    self.assertEqual(target['actual_code'], 'tiler_command_mismatch')
                    self.assertTrue(all(a['actual_status'] == 'passed' for a in
                                        result['mutation_analysis']['control']['assertions']))

    def test_live_grader_rejects_missing_coverage_guard(self):
        # Stub proves wiring and rejection, not actual agent adherence.
        for remove_guard in (False, True):
            class StubAdapter:
                executable = 'test-stub'

                @staticmethod
                def is_available():
                    return True

                @staticmethod
                def run(prompt, workspace, **kwargs):
                    if 'tiling-plan.json' not in prompt:
                        raise AssertionError('missing live task')
                    # Keep the stub independent of the reference generator.
                    plan = {
                        'preview': ['tylertoo', 'tiles', 'events.parquet', 'events.pmtiles',
                                    '--min-zoom', '4', '--max-zoom', '14', '--layer-name', 'events'],
                        'coverage': EXPECTED[:-1] if remove_guard else EXPECTED,
                        'existing': ['tippecanoe', '--output', 'cities.pmtiles', '--minimum-zoom', '0',
                                     '--maximum-zoom', '10', '--layer', 'cities', '--feature-filter',
                                     '{"*": [">", "population", 10000]}', 'cities.geojson'],
                    }
                    (workspace / 'tiling-plan.json').write_text(json.dumps(plan))
                    return AgentRunResult(agent='codex', model='test-stub', workspace=workspace,
                        duration_s=0.0, success=True, returncode=0, command=['test-stub'],
                        metadata={'structured_completion': True})

            with patch.object(eval_runner, '_load_adapter', return_value=StubAdapter()):
                result = eval_runner.run_case(CASES / '026-tiler-selection', 'live',
                    agent_override='codex', model='test-stub', skill_mode='enabled')
            self.assertEqual(result['status'], 'assertions_failed' if remove_guard else 'passed', result)
