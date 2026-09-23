"""The live-agent sandbox exposes the allowlist and nothing else.

The sandbox tests run a real Bubblewrap sandbox and skip where unprivileged
user namespaces are unavailable; the adapter itself refuses to run there.
CI sets ``OPENMAPSTACK_REQUIRE_SANDBOX=1`` so an unavailable sandbox fails
instead of skipping.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "evals"))

from adapters.isolation import PACKAGE_DIR, Sandbox, symlink_chain, unavailable_reason  # noqa: E402

UNAVAILABLE = unavailable_reason()
REQUIRED = os.environ.get("OPENMAPSTACK_REQUIRE_SANDBOX") == "1"

PROBE = """
import json, os, pathlib, sys
import openmapstack
paths = json.loads(sys.argv[1])
report = {name: os.path.exists(path) for name, path in paths.items()}
report["package"] = openmapstack.__file__
report["environment"] = sorted(os.environ)
pathlib.Path("written.txt").write_text("ok")
try:
    (pathlib.Path(openmapstack.__file__).parent / "tampered.txt").write_text("x")
    report["package_writable"] = True
except OSError:
    report["package_writable"] = False
print(json.dumps(report))
"""


class SandboxDeclarationTests(unittest.TestCase):
    def test_symlink_chain_records_each_directory_and_file_link_crossed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "python-3.12.14" / "bin").mkdir(parents=True)
            (root / "python-3.12.14" / "bin" / "python3.12").write_text("")
            (root / "python-3.12").symlink_to("python-3.12.14")
            (root / "venv").mkdir()
            (root / "venv" / "python").symlink_to(root / "python-3.12" / "bin" / "python3.12")

            chain = symlink_chain(root / "venv" / "python")

        self.assertEqual(
            chain,
            [
                (str(root / "python-3.12" / "bin" / "python3.12"), root / "venv" / "python"),
                ("python-3.12.14", root / "python-3.12"),
            ],
        )

    def test_environment_is_an_allowlist_not_the_host_environment(self) -> None:
        with patch.dict(os.environ, {"HOST_ONLY_SECRET": "leak"}):
            environment = Sandbox.for_python_agent(Path("/nonexistent"), {}).environment({"ONLY_THIS": "1"})
        self.assertEqual(environment["ONLY_THIS"], "1")
        self.assertEqual(environment["PYTHONPATH"], str(PACKAGE_DIR.parent))
        self.assertNotIn("HOST_ONLY_SECRET", environment)


@unittest.skipIf(UNAVAILABLE and not REQUIRED, f"sandbox unavailable: {UNAVAILABLE}")
class SandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        if UNAVAILABLE:
            self.fail(f"OPENMAPSTACK_REQUIRE_SANDBOX=1 but the sandbox is unavailable: {UNAVAILABLE}")

    def test_agent_sees_its_workspace_and_package_but_not_the_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openmapstack-isolation-test-") as temporary:
            base = Path(temporary).resolve()
            trial = base / "trial"
            (trial / "project").mkdir(parents=True)
            (trial / "benchmark-context").mkdir()
            outside = base / "expected-answers.json"
            outside.write_text("{}")
            sandbox = Sandbox.for_python_agent(trial, {})
            paths = {
                "guidance": str(trial / "benchmark-context"),
                "sibling_outside_trial": str(outside),
                "repo_tests": str(REPO_ROOT / "tests"),
                "repo_evals": str(REPO_ROOT / "evals"),
                "home_agent_config": str(Path.home() / ".claude"),
            }
            with patch.dict(os.environ, {"HOST_ONLY_SECRET": "leak"}):
                proc = subprocess.run(
                    [*sandbox.argv(trial / "project"), "python3", "-c", PROBE, json.dumps(paths)],
                    env=sandbox.environment({}),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            written = (trial / "project" / "written.txt").read_text()

        self.assertTrue(report["guidance"])
        self.assertFalse(report["sibling_outside_trial"])
        self.assertFalse(report["repo_tests"])
        self.assertFalse(report["repo_evals"])
        self.assertFalse(report["home_agent_config"])
        self.assertNotIn("HOST_ONLY_SECRET", report["environment"])
        self.assertEqual(Path(report["package"]).parent, PACKAGE_DIR)
        self.assertFalse(report["package_writable"])
        self.assertEqual(written, "ok")


if __name__ == "__main__":
    unittest.main()
