"""Offline healthy delivery credits, legacy compatibility and isolated defects."""
import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
import yaml
from openmapstack.credits import credit_payload

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('credits_example', ROOT / 'examples/delivery-profiles/create.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def generate(destination: Path, mutation: str | None = None, legacy: bool = False):
    path = example.create(destination, ['dashboard', 'qgis'])
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
    path.write_text(yaml.safe_dump(project, sort_keys=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--break', dest='mutation', choices=['metadata', 'missing', 'stale', 'link'])
    parser.add_argument('--legacy', action='store_true')
    args = parser.parse_args()
    generate(args.destination, args.mutation, args.legacy)
