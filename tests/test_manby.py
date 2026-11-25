"""Opt-in manby/Tippecanoe parity QA; set OMS_MANBY and OMS_TIPPECANOE.

OMS_TIPPECANOE names a pinned Tippecanoe build with tile-join beside it. CI
builds that reference, installs the checksum-verified manby release and
evals/requirements-tylertoo.txt automatically. Local runs can opt in with the
same dependencies (including Shapely and PyArrow). No network, model calls or
downloads occur in these tests.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

# Small tile-size cap forces density dropping on this modest input; the
# exclusion, type coercion and filter make attribute handling visible.
OPTIONS = ['--minimum-zoom', '0', '--maximum-zoom', '12', '--layer', 'features',
           '--drop-densest-as-needed', '--maximum-tile-bytes', '20000',
           '--exclude', 'private_note', '--attribute-type', 'code:int',
           '--feature-filter', '{"*": [">=", "value", 100]}']
SENTINEL = 'isolated-sentinel'


def features():
    """Deterministic mixed points, polygons and lines around Tartu."""
    rng = random.Random(3301)
    out = []

    def add(geometry, index):
        out.append({'type': 'Feature', 'geometry': geometry, 'properties': {
            'id': index, 'value': rng.randrange(1000), 'code': str(rng.randrange(50)),
            'name': f'f{index}', 'private_note': 'omit me'}})

    for i in range(6000):
        add({'type': 'Point', 'coordinates': [round(rng.gauss(26.72, 0.05), 6),
                                              round(rng.gauss(58.38, 0.03), 6)]}, i)
    for i in range(6000, 6300):
        x, y = round(rng.uniform(26.5, 26.9), 6), round(rng.uniform(58.3, 58.45), 6)
        add({'type': 'Polygon', 'coordinates': [[[x, y], [x + 0.002, y], [x + 0.002, y + 0.001],
                                                 [x, y + 0.001], [x, y]]]}, i)
    for i in range(6300, 6400):
        x, y = rng.uniform(26.5, 26.9), rng.uniform(58.3, 58.45)
        add({'type': 'LineString', 'coordinates': [
            [round(x + 0.003 * k, 6), round(y + rng.uniform(-0.001, 0.001), 6)] for k in range(8)]}, i)
    # Alone in its z12 tile and kept by the filter, so removing it must change output.
    out.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [27.4, 57.9]},
                'properties': {'id': 9999, 'value': 500, 'code': '1', 'name': SENTINEL,
                               'private_note': 'omit me'}})
    return out


def write_geojsonl(path, items):
    path.write_text(''.join(json.dumps(f, separators=(',', ':')) + '\n' for f in items))
    return path


def write_geoparquet(path, items):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from shapely.geometry import shape

    columns = {key: [f['properties'][key] for f in items]
               for key in ('id', 'value', 'code', 'name', 'private_note')}
    columns['geometry'] = [shape(f['geometry']).wkb for f in items]
    table = pa.table(columns)
    geo = {'version': '1.0.0', 'primary_column': 'geometry', 'columns': {'geometry': {
        'encoding': 'WKB', 'geometry_types': ['Point', 'Polygon', 'LineString']}}}
    # Omitted CRS in GeoParquet means OGC:CRS84.
    pq.write_table(table.replace_schema_metadata({b'geo': json.dumps(geo).encode()}), path)
    return path


def read_archive(path):
    """Decompressed tiles by z/x/y and metadata without writer-identity fields."""
    from pmtiles.reader import Reader, all_tiles
    from pmtiles.tile import Compression

    data = path.read_bytes()
    get_bytes = lambda offset, length: data[offset:offset + length]
    reader = Reader(get_bytes)
    compression = reader.header()['tile_compression']
    tiles = {}
    for zxy, payload in all_tiles(get_bytes):
        tiles[zxy] = gzip.decompress(payload) if compression == Compression.GZIP else payload
    # name/description default to the output file name; generator names the writer.
    metadata = {key: value for key, value in reader.metadata().items()
                if key not in {'generator', 'generator_options', 'name', 'description'}}
    return tiles, metadata


@unittest.skipUnless(os.environ.get('OMS_MANBY') and os.environ.get('OMS_TIPPECANOE'),
                     'set OMS_MANBY and OMS_TIPPECANOE for real parity QA')
class ManbyParityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manby = os.environ['OMS_MANBY']
        self.tippecanoe = os.environ['OMS_TIPPECANOE']
        self.tile_join = str(Path(self.tippecanoe).with_name('tile-join'))

    def run_tool(self, *args):
        result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def build(self, executable, source, name, options=OPTIONS):
        output = self.root / name
        self.run_tool(executable, '--quiet', '--output', output, *options, source)
        return output

    def assert_same_tiles(self, reference, candidate):
        ref_tiles, ref_meta = read_archive(reference)
        tiles, meta = read_archive(candidate)
        self.assertEqual(sorted(tiles), sorted(ref_tiles))
        self.assertEqual([zxy for zxy in sorted(ref_tiles) if ref_tiles[zxy] != tiles[zxy]], [])
        self.assertEqual(meta, ref_meta)

    def assert_meaningful(self, archive):
        """Guard against a vacuous match: dropping, exclusion and filtering happened."""
        from mapbox_vector_tile import decode

        tiles, metadata = read_archive(archive)
        self.assertGreater(len(tiles), 50)
        kept = len([f for f in features() if f['properties']['value'] >= 100])
        self.assertLess(len(decode(tiles[(0, 0, 0)])['features']['features']), kept)
        fields = metadata['vector_layers'][0]['fields']
        self.assertNotIn('private_note', fields)
        self.assertEqual(fields['code'], 'Number')
        values = [f['properties']['value'] for zxy in tiles if zxy[0] == 12
                  for f in decode(tiles[zxy])['features']['features']]
        self.assertTrue(values)
        self.assertGreaterEqual(min(values), 100)

    def test_geojson_build_matches_tippecanoe(self):
        source = write_geojsonl(self.root / 'input.geojsonl', features())
        reference = self.build(self.tippecanoe, source, 'reference.pmtiles')
        self.assert_meaningful(reference)
        self.assert_same_tiles(reference, self.build(self.manby, source, 'manby.pmtiles'))

    def test_geoparquet_input_matches_tippecanoe_geojson(self):
        items = features()
        reference = self.build(self.tippecanoe, write_geojsonl(self.root / 'input.geojsonl', items),
                               'reference.pmtiles')
        source = write_geoparquet(self.root / 'input.parquet', items)
        self.assert_same_tiles(reference, self.build(self.manby, source, 'manby.pmtiles'))

    def test_join_matches_tile_join(self):
        items = features()
        options = ['--minimum-zoom', '0', '--maximum-zoom', '10', '--drop-densest-as-needed']
        points = write_geojsonl(self.root / 'points.geojsonl',
                                [f for f in items if f['geometry']['type'] == 'Point'])
        others = write_geojsonl(self.root / 'others.geojsonl',
                                [f for f in items if f['geometry']['type'] != 'Point'])
        parts = [self.build(self.tippecanoe, points, 'points.pmtiles', [*options, '--layer', 'points']),
                 self.build(self.tippecanoe, others, 'others.pmtiles', [*options, '--layer', 'others'])]
        reference, joined = self.root / 'tile-join.pmtiles', self.root / 'manby-join.pmtiles'
        self.run_tool(self.tile_join, '--quiet', '--output', reference, *parts)
        self.run_tool(self.manby, 'join', '--quiet', '--output', joined, *parts)
        self.assertEqual({layer['id'] for layer in read_archive(reference)[1]['vector_layers']},
                         {'points', 'others'})
        self.assert_same_tiles(reference, joined)

    def test_oracle_rejects_changed_input(self):
        items = features()
        reference = self.build(self.tippecanoe, write_geojsonl(self.root / 'input.geojsonl', items),
                               'reference.pmtiles')
        missing = write_geojsonl(self.root / 'missing.geojsonl',
                                 [f for f in items if f['properties']['name'] != SENTINEL])
        with self.assertRaises(AssertionError):
            self.assert_same_tiles(reference, self.build(self.manby, missing, 'manby.pmtiles'))
