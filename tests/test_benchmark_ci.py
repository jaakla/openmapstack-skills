"""Offline tests: these must never invoke an agent or contact its provider."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import yaml

from evals import ci_preflight, report


class BenchmarkPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_missing_configuration_exports_only_a_skipped_run_with_zero_denominators(self):
        for agent, required in ci_preflight.REQUIRED.items():
            for missing in (*required, 'model'):
                with self.subTest(agent=agent, missing=missing):
                    environment = {name: 'secret-must-not-be-recorded' for name in required if name != missing}
                    output = self.root / f'{agent}-{missing}.json'
                    with redirect_stdout(io.StringIO()), patch('urllib.request.urlopen', side_effect=AssertionError('no network')):
                        ready = ci_preflight.check_configuration(agent, '' if missing == 'model' else 'exact-model', environment, output)
                    self.assertFalse(ready)
                    summary = json.loads(output.read_text())
                    self.assertTrue(summary['run_skipped'])
                    self.assertEqual(summary['results'], [])
                    self.assertEqual(summary['outcomes'], {'passed': 0, 'assertions_failed': 0, 'setup_failed': 0})
                    self.assertEqual(summary['agent_benchmark']['graded_trials'], 0)
                    self.assertEqual(summary['selection']['trials_run'], 0)
                    self.assertIsNone(summary['agent_benchmark']['task_success_rate'])
                    self.assertNotIn('secret-must-not-be-recorded', output.read_text())
                    destination = self.root / f'report-{agent}-{missing}'
                    report.export_report(summary, destination, artifact_root=self.root)
                    records = [json.loads(p.read_text()) for p in destination.glob('*-result.json')]
                    self.assertEqual([r['status'] for r in records], ['skipped'])
                    self.assertIn('Skipped / not run', (destination / 'summary.md').read_text())
                    self.assertIn('No agent was invoked', (destination / 'summary.md').read_text())

    def test_configured_provider_is_ready_without_publishing_a_success_result(self):
        for agent, required in ci_preflight.REQUIRED.items():
            output = self.root / f'{agent}.json'
            self.assertTrue(ci_preflight.check_configuration(agent, 'model', dict.fromkeys(required, 'configured'), output))
            self.assertFalse(output.exists())

    def test_run_skip_cannot_hide_graded_results(self):
        output = self.root / 'skip.json'
        with redirect_stdout(io.StringIO()):
            ci_preflight.check_configuration('codex', 'model', {}, output)
        summary = json.loads(output.read_text())
        summary['outcomes']['passed'] = 1
        from jsonschema import ValidationError
        with self.assertRaises(ValidationError):
            report.export_report(summary, self.root / 'invalid-report', artifact_root=self.root)

    def test_cli_publishes_false_output_for_unconfigured_provider(self):
        output, github_output = self.root / 'skip.json', self.root / 'github-output'
        with patch.dict(os.environ, {'GITHUB_OUTPUT': str(github_output)}, clear=True), patch('sys.argv', [
            'preflight', '--agent', 'openai_compatible', '--json', str(output),
        ]), redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(ci_preflight.main(), 0)
        self.assertEqual(github_output.read_text(), 'ready=false\n')
        self.assertIn('OPENAI_COMPATIBLE_BASE_URL', stdout.getvalue())
        self.assertIn('OPENAI_COMPATIBLE_API_KEY', stdout.getvalue())


class BenchmarkWorkflowTests(unittest.TestCase):
    def setUp(self):
        workflow = Path(__file__).resolve().parents[1] / '.github/workflows/eval-benchmark.yml'
        self.job = yaml.safe_load(workflow.read_text())['jobs']['live-benchmark']
        self.qgis_step = next(step for step in self.job['steps']
                              if step.get('name') == 'Prepare QGIS-capable Python environment')

    def test_qgis_setup_budget_fits_the_bounded_benchmark_job(self):
        self.assertEqual(self.job['timeout-minutes'], 90)
        self.assertEqual(self.qgis_step['timeout-minutes'], 20)
        self.assertLess(sum(step.get('timeout-minutes', 0) for step in self.job['steps']),
                        self.job['timeout-minutes'])

    def test_both_qgis_apt_commands_retry_with_a_bounded_http_timeout(self):
        commands = [shlex.split(line) for line in self.qgis_step['run'].splitlines()
                    if 'apt-get' in line]
        self.assertEqual(len(commands), 2)
        for action, tokens in zip(('update', 'install'), commands):
            with self.subTest(action=action):
                self.assertIn(action, tokens)
                options = list(zip(tokens, tokens[1:]))
                self.assertIn(('-o', 'Acquire::Retries=3'), options)
                self.assertIn(('-o', 'Acquire::http::Timeout=60'), options)


if __name__ == '__main__':
    unittest.main()
