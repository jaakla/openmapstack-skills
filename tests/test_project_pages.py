"""Pages retains standalone dashboards and copies complete Observable bundles."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZipFile

from scripts.build_project_pages import ROOT, build


class SkillPackageFooterTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        (self.source / "scripts").mkdir(parents=True)
        for name in ("build-claude-skill-package.sh", "sync_skill_assets.py"):
            shutil.copy2(ROOT / "scripts" / name, self.source / "scripts" / name)
        skill = self.source / "skills/demo"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Package fixture.\n---\n")
        (skill / "references/notes.md").write_text("Complete package payload.\n")
        (self.source / "collection.json").write_text(json.dumps({"skills": [
            {"name": "demo", "path": "skills/demo", "shared_references": []},
        ]}))

    def package(self, *, with_git: bool) -> str:
        # Expose only the script's runtime tools, with python3 pinned to the
        # interpreter running the tests. This reproduces the offline image's
        # missing Git without relying on the host's PATH.
        binaries = self.root / ("with-git" if with_git else "without-git")
        binaries.mkdir(exist_ok=True)
        for name in ("bash", "dirname", "mkdir", *(["git"] if with_git else [])):
            target = shutil.which(name)
            self.assertIsNotNone(target, name)
            link = binaries / name
            if not link.exists():
                link.symlink_to(target)
        (binaries / "python3").unlink(missing_ok=True)
        (binaries / "python3").symlink_to(sys.executable)
        self.assertEqual(shutil.which("git", path=str(binaries)) is not None, with_git)
        result = subprocess.run(
            [str(binaries / "bash"), str(self.source / "scripts/build-claude-skill-package.sh"),
             "--out", str(self.root / "packages")],
            env={**os.environ, "PATH": str(binaries)}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        with ZipFile(self.root / "packages/demo.zip") as archive:
            self.assertEqual(set(archive.namelist()), {"demo/SKILL.md", "demo/references/notes.md"})
            for name in archive.namelist():
                self.assertEqual(archive.read(name), (self.source / "skills" / name).read_bytes())
        return result.stdout.splitlines()[-1]

    def test_packaging_succeeds_without_git_on_path(self) -> None:
        self.assertEqual(self.package(with_git=False), "Built from source directory.")

    @unittest.skipUnless(shutil.which("git"), "checkout detection requires Git")
    def test_packaging_succeeds_outside_a_git_checkout(self) -> None:
        self.assertEqual(self.package(with_git=True), "Built from source directory.")

    @unittest.skipUnless(shutil.which("git"), "checkout footer requires Git")
    def test_checkout_footer_preserves_revision_and_dirty_status(self) -> None:
        def git(*args: str) -> str:
            return subprocess.check_output(["git", "-C", str(self.source), *args], text=True).strip()

        git("init", "-q")
        git("add", "skills", "collection.json")
        git("-c", "user.name=Package fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-qm", "Package fixture")
        revision = git("rev-parse", "--short", "HEAD")
        self.assertEqual(self.package(with_git=True), f"Built from {revision}.")
        (self.source / "skills/demo/references/notes.md").write_text("Changed package payload.\n")
        self.assertEqual(self.package(with_git=True), f"Built from {revision} plus uncommitted changes under skills/.")


class ProjectPagesTests(unittest.TestCase):
    def bundles(self, root: Path) -> Path:
        projects = root / "projects"
        for city in ("nyc", "tartu"):
            bundle = projects / city / "views/observable"
            (bundle / "_observablehq").mkdir(parents=True)
            (bundle / "index.html").write_text('<script type="module" src="./_observablehq/client.js"></script>')
            (bundle / "_observablehq/client.js").write_text("// runtime fixture")
            (bundle / "metrics.csv").write_text("id,value\nrecord,1\n")
        return projects

    def test_build_contains_both_dashboards_and_resolved_local_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            projects = self.bundles(output)
            build(output / "site", observable_projects=projects)
            output = output / "site"
            homepage = (output / "index.html").read_text(encoding="utf-8")
            renderer = (output / "langsmith/index.html").read_text(encoding="utf-8")
            self.assertIn('/* SAVED_REVIEW_DATA */ null', renderer)
            self.assertIn("Waiting for LangSmith", renderer)
            self.assertIn('href="./demos/nyc/"', homepage)
            self.assertIn('href="./demos/tartu/"', homepage)
            self.assertIn('href="#install"', homepage)
            self.assertIn('src="./installation.js"', homepage)
            for client in ("chatgpt", "codex", "cursor", "claude"):
                self.assertIn(f'aria-controls="install-{client}"', homepage)
                self.assertIn(f'id="install-{client}"', homepage)
            for city in ("nyc", "tartu"):
                self.assertIn(f'href="./demos/{city}-observable/"', homepage)
                bundle = projects / city / "views/observable"
                for source in bundle.rglob("*"):
                    if source.is_file():
                        self.assertEqual(source.read_bytes(),
                            (output / "demos" / (city + "-observable") / source.relative_to(bundle)).read_bytes())
            for relative in (
                "styles.css", "installation.js", "assets/nyc-preview.svg", "assets/tartu-preview.svg",
                "demos/nyc/index.html", "demos/tartu/index.html",
                "demos/nyc/data/derived/hub-candidates.geojson",
                "demos/nyc/data/derived/zone-metrics.geojson", ".nojekyll",
            ):
                self.assertTrue((output / relative).exists(), relative)
            self.assertEqual((ROOT / "site/installation.js").read_bytes(),
                             (output / "installation.js").read_bytes())
            collection = json.loads((ROOT / "collection.json").read_text())
            for skill in collection["skills"]:
                name = skill["name"]
                self.assertIn(f'href="./skills/{name}.zip"', homepage)
                source = ROOT / skill["path"]
                with ZipFile(output / "skills" / f"{name}.zip") as archive:
                    self.assertIn(f"{name}/SKILL.md", archive.namelist())
                    self.assertTrue(any(path.startswith(f"{name}/references/")
                                        for path in archive.namelist()))
                    # Downloads carry the actual skill payload, including supporting files.
                    for path in archive.namelist():
                        self.assertTrue(path.startswith(f"{name}/"), path)
                        self.assertEqual(archive.read(path),
                                         (source.parent / path).read_bytes())
            for example, slug in (("nyc-private-mobility", "nyc"),
                                  ("tartu-development", "tartu")):
                self.assertEqual((ROOT / "examples" / example / "dashboard.html").read_bytes(),
                                 (output / "demos" / slug / "index.html").read_bytes())
            self.assertIn("License not stated in ArcGIS item metadata",
                          (output / "demos/tartu/index.html").read_text(encoding="utf-8"))
            for name in ("nyc-preview.svg", "tartu-preview.svg"):
                preview = ElementTree.parse(output / "assets" / name).getroot()
                self.assertTrue(any(child.tag.endswith("path") for child in preview))

    def test_build_refuses_to_write_into_source_directories(self) -> None:
        for destination in (ROOT, ROOT / "site", ROOT / "examples" / "nyc-private-mobility",
                            ROOT / "examples/observable-cities", ROOT / "site/nested"):
            with self.assertRaises(ValueError):
                build(destination)

    def test_build_requires_complete_city_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self.bundles(root)
            (projects / "tartu/views/observable/index.html").unlink()
            with self.assertRaisesRegex(ValueError, "missing tartu Observable bundle"):
                build(root / "site", observable_projects=projects)

    def test_build_fails_if_skill_packaging_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self.bundles(root)
            with patch("scripts.build_project_pages.subprocess.run",
                       side_effect=subprocess.CalledProcessError(1, "skill-package")):
                with self.assertRaises(subprocess.CalledProcessError):
                    build(root / "site", observable_projects=projects)

    def test_rebuild_removes_obsolete_observable_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self.bundles(root)
            build(root / "site", observable_projects=projects)
            stale = root / "site/demos/nyc-observable/stale.js"
            stale.write_text("obsolete runtime")
            build(root / "site", observable_projects=projects)
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
