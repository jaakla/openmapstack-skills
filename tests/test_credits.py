"""Credit checks inspect rendered fields, not a renderer's receipt."""
import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import yaml

from openmapstack import credits
from openmapstack.checks.credits import declaration_valid, rendered_matches
from openmapstack.schema import project_schema_errors
from openmapstack.validation import validate_project
from openmapstack.verify import verify_project
from tests.test_delivery import example


class CreditsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = example.create(self.root, ["dashboard", "qgis"])
        subprocess.run([sys.executable, str(self.root / "pipeline.py")], check=True, capture_output=True)
        self.project = yaml.safe_load(self.path.read_text())
        self.html = self.root / self.project["outputs"]["dashboard"]["path"]
        self.qgz = self.root / self.project["outputs"]["qgis"]["path"]

    def save(self):
        self.path.write_text(yaml.safe_dump(self.project, sort_keys=False))

    def edit_qgis(self, change):
        with zipfile.ZipFile(self.qgz) as archive:
            tree = ET.fromstring(archive.read("project.qgs"))
        change(tree)
        with zipfile.ZipFile(self.qgz, "w") as archive:
            archive.writestr("project.qgs", ET.tostring(tree))

    def test_healthy_html_qgis_and_public_validation_plan(self):
        self.assertEqual(declaration_valid(self.root).status, "passed")
        self.assertEqual(rendered_matches(self.root).status, "passed")
        self.assertEqual(validate_project(self.path).status, "passed")
        planned = {c.name: c.result for c in verify_project(self.path).checks}
        self.assertEqual(planned["credits.rendered_matches"].status, "passed")
        body = self.html.read_text()
        self.assertIn("Generated with AI using the free", body)
        self.assertIn(credits.credit_payload(self.project)["analysis_at"], body)

        # An additional declared report page also needs credits, even when the
        # delivery target binds the entry dashboard separately.
        self.project["outputs"]["report"] = {"path": "report.html", "kind": "document", "format": "HTML", "generated_by": "render"}
        self.project["views"] = [{"id": "report", "output": "report", "archetype": "report"}]
        self.save()
        report = self.root / "report.html"
        report.write_text(body)
        self.assertEqual(rendered_matches(self.root).status, "passed")
        report.write_text("<html><body>Report without credits</body></html>")
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_missing_both_is_explicit_legacy_warning_but_partial_is_failed(self):
        self.project["project"].pop("author")
        self.save()
        self.assertEqual(declaration_valid(self.root).data["code"], "credits_declaration_invalid")
        self.project["project"].pop("generated_with")
        self.save()
        result = rendered_matches(self.root)
        self.assertEqual((result.status, result.data["code"]), ("warning", "credits_legacy_missing"))
        checks = {c.id: c for c in validate_project(self.path, artifacts=False).checks}
        self.assertEqual(checks["credits.declaration"].status, "warning")
        self.assertTrue(validate_project(self.path, artifacts=False).ok())

    def test_metadata_rejects_placeholders_bad_email_and_unsafe_urls(self):
        original = copy.deepcopy(self.project)
        mutations = [
            ("author", "name", "TODO-author-name"), ("author", "email", "TODO-author-email"),
            ("author", "url", "javascript:alert(1)"), ("generated_with", "url", "https://"),
            ("generated_with", "tool", "Some agent"), ("author", "url", "https://user:secret@host.invalid"),
            ("author", "url", "https://example.invalid:bad"),
            ("generated_with", "url", "https://example.invalid:99999"),
        ]
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                self.project = copy.deepcopy(original)
                self.project["project"][section][key] = value
                self.save()
                self.assertEqual(declaration_valid(self.root).status, "failed")
        self.project["project"]["author"] = "not an object"
        self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")
        self.assertTrue(project_schema_errors(self.project))

    def test_html_missing_hidden_stale_and_broken_links_fail_independently(self):
        original = self.html.read_text()
        timestamp = credits.credit_payload(self.project)["analysis_at"]
        changes = [
            lambda s: s.replace("data-openmapstack-credits", "data-removed-credits"),
            lambda s: s.replace("data-openmapstack-credits", "data-openmapstack-credits hidden"),
            lambda s: s.replace(timestamp, "2000-01-01T00:00:00+00:00"),
            lambda s: s.replace('href="mailto:examples@example.invalid"', 'href="mailto:wrong@example.invalid"'),
            lambda s: s.replace('href="https://jaakla.github.io/openmapstack-skills/"', 'href="javascript:alert(1)"'),
            lambda s: s.replace('data-oms-credit="toolkit"', 'data-oms-credit="other"'),
        ]
        for change in changes:
            self.html.write_text(change(original))
            result = rendered_matches(self.root)
            self.assertEqual((result.status, result.data["code"]), ("failed", "credits_rendered_mismatch"))
        self.html.write_text(original)
        # Correct machine datetime cannot certify stale visible time text.
        self.html.write_text(original.replace('>' + timestamp + '</time>', '>2000-01-01T00:00:00+00:00</time>'))
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_qgis_missing_stale_and_broken_links_fail(self):
        original = self.qgz.read_bytes()
        changes = [
            lambda tree: tree.remove(tree.find("projectMetadata")),
            lambda tree: setattr(tree.find("projectMetadata/author"), "text", "wrong author"),
            lambda tree: setattr(tree.find("projectMetadata/abstract"), "text", "Analysis made: 2000-01-01T00:00:00+00:00"),
            lambda tree: tree.find('projectMetadata/links/link[@name="Author email"]').set("url", "mailto:wrong@example.invalid"),
        ]
        for change in changes:
            self.qgz.write_bytes(original)
            self.edit_qgis(change)
            self.assertEqual(rendered_matches(self.root).status, "failed")
        self.qgz.write_bytes(b"broken zip")
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_credit_fields_use_visible_descendant_text(self):
        self.project['project']['author']['url'] = 'https://example.invalid/author'
        self.save()
        credits.write_qgis_credits(self.qgz, credits.credit_payload(self.project))
        body = credits.html_credits(credits.credit_payload(self.project))
        for role in ('author', 'toolkit', 'analysis', 'author-url'):
            pattern = r'(<(?:a|time) data-oms-credit="' + role + r'"[^>]*>)(.*?)(</(?:a|time)>)'
            for hidden in ('hidden', 'aria-hidden="true"', 'inert', 'style="display:none"',
                           'style="visibility:collapse"', 'style="opacity:0"'):
                with self.subTest(role=role, hidden=hidden):
                    # Visible nested markup and hidden decoration are healthy.
                    self.html.write_text(re.sub(pattern,
                        lambda m: m[1] + '<span ' + hidden + '>Decoration</span><b>' + m[2] + '</b>' + m[3], body))
                    self.assertEqual(rendered_matches(self.root).status, 'passed')
                    # Attributes/hrefs remain correct; only the field text disappears.
                    self.html.write_text(re.sub(pattern,
                        lambda m: m[1] + '<span ' + hidden + '><b>' + m[2] + '</b></span>' + m[3], body))
                    result = rendered_matches(self.root)
                    self.assertEqual((result.status, result.data['code']), ('failed', 'credits_rendered_mismatch'))
        # Mixed direct/descendant text must retain its original order.
        self.html.write_text(body.replace('>OpenMapStack</a>', '>Open<b>Map</b>Stack</a>'))
        self.assertEqual(rendered_matches(self.root).status, 'passed')

    def test_email_and_legacy_fallback_use_visible_text(self):
        body = credits.html_credits(credits.credit_payload(self.project))
        email = self.project['project']['author']['email']
        body = body.replace(' (' + email + ')</a>', '</a>')
        self.html.write_text(body.replace('</section>', '<span>' + email + '</span></section>'))
        self.assertEqual(rendered_matches(self.root).status, 'passed')
        self.html.write_text(body.replace('</section>', '<span hidden>' + email + '</span></section>'))
        result = rendered_matches(self.root)
        self.assertEqual(result.status, 'failed')
        self.assertIn('author email missing from visible credits', result.detail)
        self.project['runs']['latest'] = None
        self.save()
        credits.write_qgis_credits(self.qgz, credits.credit_payload(self.project))
        body = credits.html_credits(credits.credit_payload(self.project)).replace(' data-oms-clock-source="project.updated_at"', '')
        self.html.write_text(body)
        self.assertEqual(rendered_matches(self.root).status, 'passed')
        self.html.write_text(body.replace('no canonical run yet', '<span hidden>no canonical run yet</span>'))
        self.assertEqual(rendered_matches(self.root).status, 'failed')

    def test_inline_visibility_compares_properties_and_complete_values(self):
        panel = '<section id="panel" role="tabpanel" aria-labelledby="tab" hidden>' + credits.html_credits(credits.credit_payload(self.project)) + '</section>'
        tab = '<button id="tab" role="tab" aria-controls="panel"><span style="{}">Credits</span></button>'
        visible = ('opacity:0.5', ' OPACITY : .5 ! IMPORTANT ', 'opacity:50%', 'opacity:1e-3',
                   'opacity:0; opacity:.5', 'opacity:.5!important;opacity:0',
                   '--opacity:0', '--hint:display:none', '--hint:visibility:hidden',
                   'content:opacity:0', 'display:none-block', 'visibility:hidden-extra',
                   'opacity:0oops', 'display:none; display:block', 'visibility:hidden;visibility:visible',
                   "content:';display:none;opacity:0';opacity:.5",
                   'background:url(data:image/svg+xml;display:none;opacity:0)',
                   r"content:'escaped\';display:none;opacity:0';opacity:.5",
                   '/* opacity:0; display:none */ opacity:.5')
        hidden = ('opacity:0', ' OPACITY : 0.0 ! IMPORTANT ', 'opacity:0%', 'opacity:-0',
                  'opacity:-.5', 'opacity:0e2', 'opacity:.5;opacity:0', 'opacity:0!important;opacity:.5',
                  'display:none', ' DISPLAY : NONE ! important ', 'visibility:hidden',
                  ' VISIBILITY : COLLAPSE !important ', 'display:none!important;display:block',
                  'visibility:collapse!important;visibility:visible', 'opacity:/* zero */0')
        hidden += ('display:none;display:none-block', 'visibility:hidden;visibility:hidden-extra',
                   'opacity:0;opacity:0oops', 'display:none;display:invalid')
        for status, styles in (('passed', visible), ('failed', hidden)):
            for style in styles:
                with self.subTest(style=style, status=status):
                    self.html.write_text(tab.format(style) + panel)
                    self.assertEqual(rendered_matches(self.root).status, status)

    def test_hidden_tabpanel_requires_a_visible_enabled_associated_tab(self):
        body = credits.html_credits(credits.credit_payload(self.project))
        panel = '<section id="credits-panel" role="tabpanel" aria-labelledby="credits-tab" hidden>' + body + '</section>'
        tab = '<button id="credits-tab" role="tab" aria-controls="credits-panel" aria-selected="false">Credits</button>'
        self.html.write_text(tab + panel)
        self.assertEqual(rendered_matches(self.root).status, "passed")
        for control in (tab.replace(' aria-selected="false"', ''),
                        tab.replace('>Credits</button>', ' aria-labelledby="caption"></button>') + '<span id="caption">Credits</span>',
                        tab.replace('>Credits</button>', '><img alt="Credits"></button>')):
            self.html.write_text(control + panel)
            self.assertEqual(rendered_matches(self.root).status, 'passed')
        # The block itself can be the panel, but role alone grants no exemption.
        own_panel = body.replace('data-openmapstack-credits', 'data-openmapstack-credits role="tabpanel" hidden')
        mutations = [
            own_panel, panel, tab.replace('aria-controls="credits-panel"', 'aria-controls="other"') + panel,
            tab.replace('id="credits-tab"', 'id="other"') + panel,
            tab.replace('role="tab"', 'role="button"') + panel,
            tab.replace('role="tab"', 'role="tab" hidden') + panel,
            '<div style="display:none">' + tab + '</div>' + panel,
            tab.replace('role="tab"', 'role="tab" disabled') + panel,
            tab.replace('role="tab"', 'role="tab" aria-disabled="true"') + panel,
            '<fieldset disabled>' + tab + '</fieldset>' + panel,
            '<div aria-disabled="true">' + tab + '</div>' + panel,
            tab.replace('<button', '<input type="hidden"').replace('</button>', '') + panel,
            tab.replace('aria-selected="false"', 'aria-selected="true"') + panel,
            tab + tab + panel, tab + panel + panel,
            panel.replace(body, tab + body),  # Its only control is unreachable inside it.
            '<div inert>' + tab + panel + '</div>',
            tab + panel.replace(body, body.replace('data-openmapstack-credits', 'data-openmapstack-credits hidden')),
        ]
        for index, html in enumerate(mutations):
            with self.subTest(index=index):
                self.html.write_text(html)
                result = rendered_matches(self.root)
                self.assertEqual((result.status, result.data["code"]), ("failed", "credits_rendered_mismatch"))

    def test_implicit_tab_name_excludes_hidden_descendants(self):
        panel = '<section id="panel" role="tabpanel" aria-labelledby="tab" hidden>' + credits.html_credits(credits.credit_payload(self.project)) + '</section>'
        tab = '<button id="tab" role="tab" aria-controls="panel">{}</button>'
        self.html.write_text(tab.format('').replace('<button ', '<button alt="Credits" ') + panel)
        self.assertEqual(rendered_matches(self.root).status, 'failed')
        for content in ('<span hidden>Credits</span>', '<span aria-hidden="true">Credits</span>',
                        '<span style="display:none">Credits</span>', '<span inert>Credits</span>',
                        '<span hidden><b>Credits</b></span>', '<img hidden alt="Credits">',
                        '<span hidden><img alt="Credits"></span>'):
            with self.subTest(content=content):
                self.html.write_text(tab.format(content) + panel)
                self.assertEqual(rendered_matches(self.root).status, 'failed')
        for content in ('<span hidden>Decoration</span><b>Credits</b>',
                        '<span hidden>Decoration</span>Credits', '<img alt="Credits">'):
            with self.subTest(content=content):
                self.html.write_text(tab.format(content) + panel)
                self.assertEqual(rendered_matches(self.root).status, 'passed')

    def test_qgis_header_author_matches_independently_of_native_author(self):
        original = self.qgz.read_bytes()
        author = self.project['project']['author']
        value = f"{author['name']} ({author['email']})"
        for line in ('Autor: ' + value + '.', value, '作者: ' + value):
            self.qgz.write_bytes(original)
            def replace_header(tree):
                abstract = tree.find('projectMetadata/abstract')
                lines = abstract.text.splitlines()
                lines[2] = line
                abstract.text = '\n'.join(lines)
            self.edit_qgis(replace_header)
            self.assertEqual(rendered_matches(self.root).status, 'passed')
        for line in ('Autor: Wrong author (wrong@example.invalid)',
                     f"Autor: Wrong author ({author['email']})",
                     f"Autor: {author['name']} (wrong@example.invalid)",
                     'Autor: Prefix ' + value, 'Autor: ' + value + ' and another author', ''):
            with self.subTest(line=line):
                self.qgz.write_bytes(original)
                self.edit_qgis(replace_header)
                with zipfile.ZipFile(self.qgz) as archive:
                    self.assertEqual(ET.fromstring(archive.read('project.qgs')).findtext('projectMetadata/author'), value)
                result = rendered_matches(self.root)
                self.assertEqual(result.status, 'failed')
                self.assertIn('QGIS credit header author differs', result.detail)

    def test_translated_qgis_header_binds_identity_clock_and_links(self):
        original = self.qgz.read_bytes()
        def translate(tree):
            abstract = tree.find('projectMetadata/abstract')
            abstract.text = abstract.text.replace('Generated with AI using the free OpenMapStack toolkit.',
                'Koostatud tehisintellekti abil tasuta OpenMapStack tööriistakomplektiga.').replace(
                'Analysis made:', 'Analüüs tehtud:').replace('Author:', 'Autor:')
            # Source timestamps elsewhere are not the analysis completion time.
            abstract.text += '\nAllikas laaditud: 2020-01-01T00:00:00+00:00'
            for link in tree.findall('projectMetadata/links/link'):
                link.set('name', 'Tõlgitud viide')
        self.edit_qgis(translate)
        translated = self.qgz.read_bytes()
        self.assertEqual(rendered_matches(self.root).status, 'passed')
        timestamp = credits.credit_payload(self.project)['analysis_at']
        mutations = [
            lambda tree: setattr(tree.find('projectMetadata/author'), 'text', 'Vale autor'),
            lambda tree: setattr(tree.find('projectMetadata/abstract'), 'text',
                tree.findtext('projectMetadata/abstract').replace('OpenMapStack', 'Other toolkit')),
            lambda tree: setattr(tree.find('projectMetadata/abstract'), 'text',
                tree.findtext('projectMetadata/abstract').replace(timestamp, '2000-01-01T00:00:00+00:00')),
            lambda tree: setattr(tree.find('projectMetadata/abstract'), 'text',
                tree.findtext('projectMetadata/abstract').replace(timestamp, '2000-01-01T00:00:00')),
            lambda tree: setattr(tree.find('projectMetadata/abstract'), 'text',
                tree.findtext('projectMetadata/abstract').replace('[clock:runs.latest.completed_at]', '[clock:project.updated_at]')),
            lambda tree: setattr(tree.find('projectMetadata/abstract'), 'text',
                tree.findtext('projectMetadata/abstract').replace('[clock:runs.latest.completed_at]', '[clock:]')),
            lambda tree: tree.find('projectMetadata/links/link[@url="https://jaakla.github.io/openmapstack-skills/"]').set('url', 'https://wrong.invalid'),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                self.qgz.write_bytes(translated)
                self.edit_qgis(mutation)
                self.assertEqual(rendered_matches(self.root).status, 'failed')
        self.qgz.write_bytes(translated)
        credits.write_qgis_credits(self.qgz, credits.credit_payload(self.project))
        with zipfile.ZipFile(self.qgz) as archive:
            abstract = ET.fromstring(archive.read('project.qgs')).findtext('projectMetadata/abstract')
        self.assertEqual(abstract.count('[clock:runs.latest.completed_at]'), 1)
        self.assertNotIn('Analüüs tehtud:', abstract)
        self.assertIn('Allikas laaditud:', abstract)
        self.qgz.write_bytes(original)
        # Existing canonical headers without the new clock marker still work.
        self.edit_qgis(lambda tree: setattr(tree.find('projectMetadata/abstract'), 'text',
            tree.findtext('projectMetadata/abstract').replace(' [clock:runs.latest.completed_at]', '')))
        self.edit_qgis(translate)
        self.assertEqual(rendered_matches(self.root).status, 'passed')

    def test_translated_prerun_fallback_keeps_language_independent_clock_source(self):
        self.project['runs']['latest'] = None
        self.save()
        payload = credits.credit_payload(self.project)
        body = credits.html_credits(payload).replace('project updated time; no canonical run yet',
            'projekti uuendamise aeg; kanooniline käivitus puudub')
        self.html.write_text(body)
        credits.write_qgis_credits(self.qgz, payload)
        self.edit_qgis(lambda tree: setattr(tree.find('projectMetadata/abstract'), 'text',
            tree.findtext('projectMetadata/abstract').replace('Analysis made:', 'Analüüs tehtud:').replace(
                'project updated time; no canonical run yet', 'projekti uuendamise aeg; kanooniline käivitus puudub')))
        self.assertEqual(rendered_matches(self.root).status, 'passed')
        self.html.write_text(body.replace('data-oms-clock-source="project.updated_at"',
                                         'data-oms-clock-source="runs.latest.completed_at"'))
        self.assertEqual(rendered_matches(self.root).status, 'failed')

    def test_attribution_prose_is_an_authoring_and_visual_requirement(self):
        body = self.html.read_text().replace('Generated with AI using the free ', '').replace(' toolkit.</p>', '</p>')
        self.html.write_text(body)
        # The bounded checker certifies fields/links, not multilingual meaning.
        self.assertEqual(rendered_matches(self.root).status, 'passed')
        self.assertIn('Generated with AI using the free ', credits.html_credits(credits.credit_payload(self.project)))

    def test_author_and_clock_changes_require_new_rendered_credits(self):
        # A shorter name must not pass by matching a substring of stale text.
        self.project["project"]["author"]["name"] = "OpenMapStack"
        self.save()
        self.assertEqual(rendered_matches(self.root).status, "failed")
        self.project["project"]["author"]["name"] = "A different analyst"
        self.save()
        self.assertEqual(rendered_matches(self.root).status, "failed")
        self.project["runs"]["latest"]["completed_at"] = "2026-10-16T17:00:00"
        self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")
        self.project["runs"]["latest"].pop("completed_at")
        self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")

    def test_labeled_prerun_fallback_optional_site_and_escaping(self):
        self.project["runs"]["latest"] = None
        self.project["project"]["author"].update(name='<script>alert("author")</script>', url="https://example.invalid/author?a=1&b=2")
        self.project["project"]["updated_at"] = "2026-10-16T20:30:00+03:00"
        self.save()
        values = credits.credit_payload(self.project)
        body = credits.html_credits(values)
        self.assertNotIn('<script>', body)
        self.assertIn('no canonical run yet', body)
        self.html.write_text(body)
        credits.write_qgis_credits(self.qgz, values)
        self.assertEqual(rendered_matches(self.root).status, "passed")
        self.html.write_text(body.replace('href="https://example.invalid/author?a=1&amp;b=2"', 'href="https://wrong.invalid"'))
        self.assertEqual(rendered_matches(self.root).status, "failed")

    def test_no_views_and_legacy_known_paths_missing_files_and_malformed_inputs(self):
        self.project.pop("delivery")
        self.save()
        self.assertEqual(rendered_matches(self.root).status, "passed")
        self.html.unlink()
        self.assertEqual(rendered_matches(self.root).status, "failed")
        self.project["outputs"] = {}; self.qgz.unlink(); self.project["presentation"].pop("dashboard", None)
        self.save()
        result = rendered_matches(self.root)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.data["surfaces"], [])
        self.project["project"] = None; self.save()
        self.assertEqual(declaration_valid(self.root).status, "failed")
        self.path.unlink()
        self.assertEqual(rendered_matches(self.root).data["code"], "manifest_missing")

    def test_qgis_updater_keeps_findings_attachments_and_zip_dates(self):
        values = credits.credit_payload(self.project)
        with zipfile.ZipFile(self.qgz, "a") as archive:
            archive.writestr("styles.db", b"synthetic attachment")
        credits.write_qgis_credits(self.qgz, values)
        credits.write_qgis_credits(self.qgz, values)
        with zipfile.ZipFile(self.qgz) as archive:
            self.assertEqual(archive.read("styles.db"), b"synthetic attachment")
            tree = ET.fromstring(archive.read("project.qgs"))
        self.assertEqual(len(tree.findall('projectMetadata/links/link[@name="Author email"]')), 1)
        self.assertIsNotNone(tree.find('projectMetadata/links/link[@name="Findings"]'))
        qgs = self.root / "companion.qgs"
        qgs.write_bytes(ET.tostring(tree))
        credits.write_qgis_credits(qgs, values)
        self.assertIn(values["analysis_at"], qgs.read_text())
