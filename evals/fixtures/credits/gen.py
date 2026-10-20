"""Offline healthy delivery credits, legacy compatibility and isolated defects."""
import argparse
import importlib.util
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
import yaml
from openmapstack.credits import credit_payload

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('credits_example', ROOT / 'examples/delivery-profiles/create.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def generate(destination: Path, mutation: str | None = None, legacy: bool = False, translated: bool = False,
             nested_fields: bool = False, opacity_tab: bool = False):
    path = example.create(destination, ['dashboard', 'qgis'])
    if translated:
        pipeline = path.parent / 'pipeline.py'
        # Translation is part of this fixture's canonical pipeline, before run
        # hashing. The healthy translated control must have truthful evidence.
        wrapper = '''
_english_qgis_credits = qgis_credits
def qgis_credits(xml, payload):
    return _english_qgis_credits(xml, payload).replace(
        'Generated with AI using the free OpenMapStack toolkit.',
        'Koostatud tehisintellekti abil tasuta OpenMapStack tööriistakomplektiga.').replace(
        'Analysis made:', 'Analüüs tehtud:').replace('Author:', 'Autor:')

'''
        original = pipeline.read_text()
        marker = 'if __name__ == "__main__":'
        assert marker in original
        pipeline.write_text(original.replace(marker, wrapper + marker))
    if nested_fields or opacity_tab:
        pipeline = path.parent / 'pipeline.py'
        # Controls render their nested fields/tab before canonical run hashing.
        wrapper = '''
_plain_html_credits = html_credits
def html_credits(payload):
    import re
    body = _plain_html_credits(payload)
'''
        if nested_fields:
            wrapper += '''
    body = re.sub(r'(<(?:a|time) data-oms-credit="(?:author|toolkit|analysis)"[^>]*>)(.*?)(</(?:a|time)>)',
        lambda m: m[1] + '<span>' + m[2] + '</span>' + m[3], body)
'''
        if opacity_tab:
            wrapper += '''
    body = ('<button id="credits-tab" role="tab" aria-controls="credits-panel"><span style="opacity:0.5">Credits</span></button>'
            '<section id="credits-panel" role="tabpanel" aria-labelledby="credits-tab" hidden>' + body + '</section>')
'''
        wrapper += '    return body\n\n'
        original = pipeline.read_text()
        marker = 'if __name__ == "__main__":'
        assert marker in original
        pipeline.write_text(original.replace(marker, wrapper + marker))
    subprocess.run([sys.executable, str(path.parent / 'pipeline.py')], check=True)
    project = yaml.safe_load(path.read_text())
    page = path.parent / project['outputs']['dashboard']['path']
    if legacy:
        project['project'].pop('author')
        project['project'].pop('generated_with')
    elif mutation == 'metadata':
        project['project'].pop('author')
    elif mutation == 'missing':
        page.write_text(re.sub(r'<section data-openmapstack-credits.*?</section>', '', page.read_text(), flags=re.S))
    elif mutation == 'stale':
        page.write_text(page.read_text().replace(credit_payload(project)['analysis_at'], '2000-01-01T00:00:00+00:00'))
    elif mutation == 'link':
        page.write_text(page.read_text().replace('href="mailto:examples@example.invalid"', 'href="mailto:wrong@example.invalid"'))
    elif mutation == 'tabpanel':
        page.write_text(page.read_text().replace('data-openmapstack-credits', 'data-openmapstack-credits role="tabpanel" hidden'))
    elif mutation == 'css-fields':
        page.write_text('<style>[data-oms-credit=toolkit] span { opacity:0 }</style>' + page.read_text())
    elif mutation == 'hidden-fields':
        page.write_text(page.read_text().replace('<span>', '<span hidden>'))
    elif mutation == 'tab-opacity':
        page.write_text(page.read_text().replace('style="opacity:0.5"', 'style="opacity:0"'))
    elif mutation == 'tab-label':
        body = page.read_text()
        body = re.sub(r'(<section data-openmapstack-credits.*?</section>)',
            r'<button id="credits-tab" role="tab" aria-controls="credits-panel"><span hidden>Credits</span></button>'
            r'<section id="credits-panel" role="tabpanel" aria-labelledby="credits-tab" hidden>\1</section>', body, flags=re.S)
        page.write_text(body)
    elif mutation in {'qgis-time', 'qgis-identity', 'qgis-link', 'qgis-header-author'}:
        archive_path = path.parent / project['outputs']['qgis']['path']
        with zipfile.ZipFile(archive_path) as archive:
            members = [(info, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(archive_path, 'w') as archive:
            for info, data in members:
                if info.filename.endswith('.qgs'):
                    tree = ET.fromstring(data)
                    if mutation == 'qgis-time':
                        abstract = tree.find('projectMetadata/abstract')
                        abstract.text = abstract.text.replace(credit_payload(project)['analysis_at'], '2000-01-01T00:00:00+00:00')
                    elif mutation == 'qgis-identity':
                        tree.find('projectMetadata/author').text = 'Vale autor'
                    elif mutation == 'qgis-header-author':
                        abstract = tree.find('projectMetadata/abstract')
                        lines = abstract.text.splitlines()
                        lines[2] = 'Autor: Wrong author (wrong@example.invalid)'
                        abstract.text = '\n'.join(lines)
                    else:
                        tree.find('projectMetadata/links/link[@url="https://jaakla.github.io/openmapstack-skills/"]').set('url', 'https://wrong.invalid')
                    data = ET.tostring(tree)
                archive.writestr(info, data)
    path.write_text(yaml.safe_dump(project, sort_keys=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--break', dest='mutation', choices=['metadata', 'missing', 'stale', 'link', 'tabpanel', 'tab-label', 'hidden-fields', 'tab-opacity', 'css-fields', 'qgis-time', 'qgis-identity', 'qgis-link', 'qgis-header-author'])
    parser.add_argument('--legacy', action='store_true')
    parser.add_argument('--translated', action='store_true')
    parser.add_argument('--nested-fields', action='store_true')
    parser.add_argument('--opacity-tab', action='store_true')
    args = parser.parse_args()
    generate(args.destination, args.mutation, args.legacy, args.translated, args.nested_fields, args.opacity_tab)
