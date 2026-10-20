"""Computed credits visibility; optional Chromium tests skip in core-only installs."""
import html
import tempfile
import unittest
from pathlib import Path

import yaml
from openmapstack.credits import credit_payload, html_credits
from openmapstack.checks.visual import credits_visible_in_browser


class CreditsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as runtime:
                runtime.chromium.launch().close()
        except Exception as exc:
            raise unittest.SkipTest(f'Playwright Chromium unavailable: {exc}')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = {'project': {'author': {'name': 'Analyst', 'email': 'analyst@example.invalid',
                            'url': 'https://example.invalid/author'},
                         'generated_with': {'tool': 'OpenMapStack', 'url': 'https://example.invalid/oms'},
                         'updated_at': '2026-10-20T12:00:00+00:00'}}
        (self.root/'project.yaml').write_text(yaml.safe_dump(self.project))
        self.body = html_credits(credit_payload(self.project))

    def check(self, body, status):
        (self.root/'dashboard.html').write_text(body)
        result = credits_visible_in_browser(self.root)
        self.assertEqual(result.status, status, result.detail)

    def test_stylesheets_hidden_descendants_and_all_fields(self):
        self.check(self.body, 'passed')
        for role in ('toolkit', 'author', 'analysis', 'author-url'):
            with self.subTest(role=role):
                self.check('<style>[data-oms-credit="'+role+'"]{opacity:0}</style>'+self.body, 'failed')
        self.check('<style>[data-openmapstack-credits]{visibility:hidden}</style>'+self.body, 'failed')
        self.check('<style>[data-openmapstack-credits]{opacity:0}</style>'+self.body, 'failed')
        self.check(self.body.replace(' (analyst@example.invalid)',
            '<span style="opacity:0"> (analyst@example.invalid)</span>'), 'failed')
        nested = self.body.replace('>OpenMapStack</a>', '><span class="value">OpenMapStack</span></a>')
        self.check('<style>.value{opacity:0}</style>'+nested, 'failed')
        self.check('<style>.value{opacity:.5}</style>'+nested, 'passed')
        self.check(self.body.replace('>OpenMapStack</a>', '><span hidden>Decoration</span>OpenMapStack</a>'), 'passed')

    def test_browser_resolves_the_three_static_qa_deferrals(self):
        for style, status in [('--a:"/*";opacity:0;--b:"*/"', 'failed'),
                              ('opacity:0;opacity:initial', 'passed'),
                              ('display:none;display:flow-root list-item', 'passed')]:
            with self.subTest(style=style):
                self.check(self.body.replace('>OpenMapStack</a>',
                    '><span style="'+html.escape(style, quote=True)+'">OpenMapStack</span></a>'), status)

    def test_tab_is_opened_and_its_handler_must_work(self):
        panel = '<section id="panel" role="tabpanel" aria-labelledby="tab" hidden>'+self.body+'</section>'
        tab = '<button id="tab" role="tab" aria-controls="panel" onclick="document.getElementById(\'panel\').hidden=false">Credits</button>'
        self.check(tab+panel, 'passed')
        self.check(tab.replace('hidden=false', 'hidden=true')+panel, 'failed')
