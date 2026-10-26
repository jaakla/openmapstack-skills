"""Real reference-dashboard CSS against the unchanged browser bounds check."""
from __future__ import annotations

import importlib.util
import unittest

from openmapstack.checks import visual
from tests.evals.helpers import EVALS_DIR, make_workspace, minimal_project


class FixtureDashboardLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            raise unittest.SkipTest('Playwright unavailable')
        cls.runtime = sync_playwright().start()
        cls.addClassCleanup(cls.runtime.stop)
        try:
            cls.browser = cls.runtime.chromium.launch()
        except Error as error:
            raise unittest.SkipTest(f'Chromium unavailable: {error}')
        cls.addClassCleanup(cls.browser.close)
        spec = importlib.util.spec_from_file_location(
            'fixture_dashboard_generator', EVALS_DIR / 'fixtures/reference_pipeline/gen.py')
        cls.generator = importlib.util.module_from_spec(spec)
        if importlib.util.find_spec('duckdb') is None:
            raise unittest.SkipTest('DuckDB unavailable for the reference generator')
        spec.loader.exec_module(cls.generator)

    def dashboard(self, defect=None):
        root = make_workspace()
        project = minimal_project()
        project['project'].update(
            author={'name': 'Test author', 'email': 'author@example.invalid'},
            generated_with={'tool': 'OpenMapStack', 'url': 'https://example.invalid/toolkit'})
        project['presentation']['controls'] = {'scenarios': []}
        project['presentation']['map']['layer_groups'] = [{'id': 'analysis', 'title': 'Analysis'}]
        # Layout is independent of provider availability. Retain the real
        # MapLibre renderer and attribution control, with an offline raster.
        project['presentation']['map']['basemap']['tiles'] = [
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1sAAAAASUVORK5CYII=']
        self.generator._copy_vendored_maplibre(root)
        (root / 'dashboard.html').write_text(self.generator._build_dashboard_html(root, project, defect))
        return root

    def inspect(self, root, width, height):
        page = self.browser.new_page(viewport={'width': width, 'height': height})
        self.addCleanup(page.close)
        page.goto((root / 'dashboard.html').as_uri(), wait_until='domcontentloaded')
        page.wait_for_selector('.maplibregl-ctrl-attrib')
        return page

    def test_reference_controls_fit_desktop_and_mobile(self):
        root = self.dashboard()
        for width, height in ((1440, 900), (390, 844), (320, 568)):
            with self.subTest(viewport=(width, height)):
                page = self.inspect(root, width, height)
                try:
                    self.assertEqual(visual._dashboard_layout_problems(page), [])
                finally:
                    page.close()

    def test_mobile_map_precedes_a_scrollable_sidebar_and_controls_remain_usable(self):
        page = self.inspect(self.dashboard(), 390, 844)
        map_box, sidebar = page.locator('#map').bounding_box(), page.locator('#sidebar').bounding_box()
        self.assertEqual(map_box['x'], 0)
        self.assertEqual(map_box['width'], 390)
        self.assertGreaterEqual(map_box['height'], 280)
        self.assertGreaterEqual(sidebar['y'], map_box['y'] + map_box['height'])
        self.assertEqual(page.locator('#sidebar').evaluate('e => getComputedStyle(e).overflowY'), 'auto')
        toggle = page.locator('[data-layer-group="analysis"]')
        toggle.uncheck()
        page.locator('#reset').click()
        self.assertTrue(toggle.is_checked())
        self.assertEqual(page.evaluate('scrollY'), 0)

    def test_original_mobile_overflow_mutation_still_fails_strict_bounds(self):
        root = self.dashboard('dashboard_mobile_controls_overflow')
        desktop = self.inspect(root, 1440, 900)
        self.assertEqual(visual._dashboard_layout_problems(desktop), [])
        desktop.close()
        mobile = self.inspect(root, 390, 844)
        self.assertIn('map legend or controls extend outside the map', visual._dashboard_layout_problems(mobile))
