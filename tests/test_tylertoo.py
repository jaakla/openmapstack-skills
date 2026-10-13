"""Opt-in real tiler QA; set OMS_TYLERTOO to a verified release executable.

CI installs the pinned release and evals/requirements-tylertoo.txt automatically.
Local runs can opt in with the same dependencies (including Shapely).
No network, model calls or downloads occur in these tests.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('OMS_TYLERTOO'), 'set OMS_TYLERTOO for real tiler QA')
class TylertooTests(unittest.TestCase):
    def run_tool(self, *args):
        result = subprocess.run(
            [os.environ['OMS_TYLERTOO'], *map(str, args)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def write_source(self, root):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from shapely.geometry import box

        # Synthetic adjoining polygons away from tile boundaries at z4/z5.
        # Unequal values make dropped properties or swapped associations visible.
        table = pa.table({
            'id': pa.array([101, 202], type=pa.uint64()),
            'value': [7, 19],
            'private_note': ['omit me', 'omit me too'],
            'geometry': [box(24.2, 59.1, 24.3, 59.2).wkb,
                         box(24.3, 59.1, 24.4, 59.2).wkb],
        })
        geo = {'version': '1.0.0', 'primary_column': 'geometry', 'columns': {
            'geometry': {'encoding': 'WKB', 'geometry_types': ['Polygon'],
                         'bbox': [24.2, 59.1, 24.4, 59.2]}}}
        # Omitted CRS in GeoParquet means OGC:CRS84.
        table = table.replace_schema_metadata({b'geo': json.dumps(geo).encode()})
        source = root / 'input.parquet'
        pq.write_table(table, source)
        return source

    def check_archive(self, path):
        from mapbox_vector_tile import decode
        from pmtiles.reader import Reader, all_tiles
        from pmtiles.tile import Compression

        data = path.read_bytes()
        get_bytes = lambda offset, length: data[offset:offset + length]
        reader = Reader(get_bytes)
        header = reader.header()
        self.assertEqual((header['min_zoom'], header['max_zoom']), (4, 5))
        self.assertEqual([layer['id'] for layer in reader.metadata()['vector_layers']], ['coverage'])
        seen = {4: {}, 5: {}}
        for (zoom, _, _), payload in all_tiles(get_bytes):
            if header['tile_compression'] == Compression.GZIP:
                payload = gzip.decompress(payload)
            else:
                self.assertEqual(header['tile_compression'], Compression.NONE)
            layers = decode(payload)
            self.assertEqual(set(layers), {'coverage'})
            for feature in layers['coverage']['features']:
                props = feature['properties']
                self.assertNotIn('private_note', props)
                # The selected ID column is promoted to the MVT feature ID.
                self.assertEqual(feature['geometry']['type'], 'Polygon')
                self.assertTrue(feature['geometry']['coordinates'])
                seen[zoom][feature['id']] = props['value']
        self.assertEqual(seen, {4: {101: 7, 202: 19}, 5: {101: 7, 202: 19}})

    def test_direct_and_overview_exports_preserve_coverage_and_properties(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            overview = root / 'overview.parquet'
            flags = ['--min-zoom', '4', '--max-zoom', '5', '--verbatim',
                     '--include-property', 'id', '--include-property', 'value']
            export = ['--layer-name', 'coverage', '--feature-id', 'id']
            self.run_tool('tiles', source, root / 'direct.pmtiles', *flags, *export)
            self.check_archive(root / 'direct.pmtiles')
            self.run_tool('overview', source, overview, *flags)
            self.run_tool('validate', overview)
            self.run_tool('export-pmtiles', overview, root / 'overview.pmtiles', *export)
            self.check_archive(root / 'overview.pmtiles')

    def test_oracle_rejects_missing_polygon(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            table = pq.read_table(source)
            pq.write_table(table.slice(0, 1), source)
            self.run_tool('tiles', source, root / 'missing.pmtiles',
                          '--min-zoom', '4', '--max-zoom', '5', '--verbatim',
                          '--layer-name', 'coverage', '--feature-id', 'id',
                          '--include-property', 'id', '--include-property', 'value')
            with self.assertRaises(AssertionError):
                self.check_archive(root / 'missing.pmtiles')
