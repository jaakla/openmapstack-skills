#!/usr/bin/env python3
"""Small real DuckDB transform and GDAL-export axis-order mutation twins."""
from pathlib import Path
import argparse
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--break', dest='defect', choices=['missing', 'wrong'])
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
# Static missing-setting evidence does not execute broken SQL: DuckDB 2.0
# correctly refuses it. The wrong-axis twin executes real, misplaced output.
setup = '' if args.defect == 'missing' else 'configure_spatial_axes(con)'
if args.defect == 'wrong':
    setup += '''
if con.execute("SELECT name FROM duckdb_settings() WHERE name='geometry_always_xy'").fetchone():
    con.execute("SET geometry_always_xy = false")
'''
from openmapstack.checks.spatial import require_spatial
probe = require_spatial()
has_setting = bool(probe.execute("SELECT name FROM duckdb_settings() WHERE name='geometry_always_xy'").fetchone())
probe.close()
# Modern twins differ only in connection setup. Pre-1.5 needs per-call axes.
axes = '' if has_setting else ', always_xy := ' + ('false' if args.defect == 'wrong' else 'true')
export_path = (args.output / 'point.gpkg').resolve().as_posix().replace("'", "''")
export_sql = ("COPY (SELECT ST_Transform(ST_Point(2755558.1473003766, 8275444.877846606), "
              "'EPSG:3857', 'EPSG:4326'" + axes + ") AS geom) TO '" + export_path +
              "' (FORMAT GDAL, DRIVER 'GPKG', SRS 'EPSG:4326')")
script = '''import json
from pathlib import Path
import duckdb
from openmapstack.checks.spatial import configure_spatial_axes
from openmapstack.checks.spatial import _connection_config
con = duckdb.connect(config=_connection_config())
con.execute("LOAD spatial")
SETUP
# The projected point is an independent Web Mercator oracle for Tallinn.
row = con.execute("SELECT ST_AsGeoJSON(ST_Transform(ST_Point(2755558.1473003766, 8275444.877846606), 'EPSG:3857', 'EPSG:4326'AXES))").fetchone()
Path(__file__).with_name('point.json').write_text(json.dumps({'point': json.loads(row[0])}))
con.execute(EXPORT_SQL)
con.close()
'''.replace('SETUP', setup).replace('AXES', axes).replace('EXPORT_SQL', repr(export_sql))
(args.output / 'pipeline.py').write_text(script)
if args.defect != 'missing':
    subprocess.run([sys.executable, str((args.output / 'pipeline.py').resolve())], check=True)
