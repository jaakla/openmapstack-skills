"""Deterministic command-plan control; does not execute any external tiler."""
import argparse
import json
from pathlib import Path


def generate(root, mutation=None):
    plan = {
        'preview': ['tylertoo', 'tiles', 'events.parquet', 'events.pmtiles',
                    '--min-zoom', '4', '--max-zoom', '14', '--layer-name', 'events'],
        'coverage': ['tylertoo', 'tiles', 'cells.parquet', 'cells.pmtiles',
                     '--min-zoom', '4', '--max-zoom', '8', '--layer-name', 'cells', '--verbatim'],
        'existing': ['tippecanoe', '--output', 'cities.pmtiles', '--minimum-zoom', '0',
                     '--maximum-zoom', '10', '--layer', 'cities', '--feature-filter',
                     '{"*": [">", "population", 10000]}', 'cities.geojson'],
    }
    if mutation == 'wrong-tool':
        plan['preview'] = ['tippecanoe', '--output', 'events.pmtiles',
                           '--minimum-zoom', '4', '--maximum-zoom', '14',
                           '--layer', 'events', 'events.parquet']
    elif mutation == 'thinning':
        plan['coverage'].remove('--verbatim')
    elif mutation == 'replace-existing':
        plan['existing'] = ['tylertoo', 'tiles', 'cities.geojson', 'cities.pmtiles']
    root.mkdir(parents=True, exist_ok=True)
    (root / 'tiling-plan.json').write_text(json.dumps(plan, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--mutation', choices=['wrong-tool', 'thinning', 'replace-existing'])
    args = parser.parse_args()
    generate(args.root, args.mutation)
