"""Deterministic command-plan control; does not execute any external tiler."""
import argparse
import json
from pathlib import Path


def generate(root, mutation=None):
    # Same options as the tuned Tippecanoe build; only the executable changes.
    plan = {
        'accelerated': ['manby', '--output', 'buildings.pmtiles', '--minimum-zoom', '10',
                        '--maximum-zoom', '14', '--layer', 'buildings',
                        '--drop-densest-as-needed', 'buildings.geojsonl'],
    }
    if mutation == 'output-change':
        # A manby-only switch that makes tiles differ from Tippecanoe's.
        plan['accelerated'].insert(-1, '--as-needed-per-tile')
    elif mutation == 'generalization-change':
        # A different tiler with its own generalization is not a like-for-like swap.
        plan['accelerated'] = ['tylertoo', 'tiles', 'buildings.geojsonl', 'buildings.pmtiles',
                               '--min-zoom', '10', '--max-zoom', '14',
                               '--layer-name', 'buildings']
    root.mkdir(parents=True, exist_ok=True)
    (root / 'tiling-plan.json').write_text(json.dumps(plan, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--mutation', choices=['output-change', 'generalization-change'])
    args = parser.parse_args()
    generate(args.root, args.mutation)
