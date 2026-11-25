# manby parity review

The shared [web-delivery guidance](../skills/open-map-stack/references/web-delivery.md#manby--the-same-options-on-a-faster-engine)
adds manby as a different executable for Tippecanoe's options. It adds no new
project contract or generalization choice. Three planning cases measure whether
an agent keeps a tuned Tippecanoe build unchanged when it switches engines.
Case `032-tiler-compatible-engine` asks for the faster engine with the same
options. Mutation `953` adds a manby-only option that changes tiles, and
mutation `954` swaps in tylertoo, which has its own generalization. Each must be
rejected against a healthy control. The bounded argv grader treats the
executable as part of the decision, so a plan that keeps `tippecanoe` also fails
`032`. Case `026` still requires the existing Tippecanoe workflow where no
migration is requested. This is planning coverage, not evidence of execution.

```bash
python3 evals/run.py --mode fixture --case 032-tiler-compatible-engine \
  --case 953-tiler-engine-output-change --case 954-tiler-engine-generalization-change
```

The fixture controls and a stub live adapter in `tests/evals/test_tiling.py`
test the grader without model calls. Live-agent runs remain subject to the
explicit model/budget policy in `AGENTS.md`.

## Executable parity check

`tests/test_manby.py` writes deterministic mixed points, polygons and lines. A
small tile-size cap forces density dropping, and an exclusion, a type coercion
and a feature filter make attribute handling visible. The test builds the same
arguments with Tippecanoe and manby and requires the same tile set,
byte-identical decompressed tiles and the same metadata. The writer name, the
options it records, and the name and description (which default to the output
file name) are excluded. The test also checks that the match is not vacuous:
dropping, exclusion and filtering must actually have happened. It repeats the
comparison for GeoParquet input to manby against GeoJSON input to Tippecanoe,
and for `manby join` against `tile-join`. A negative control removes one
isolated feature from manby's input; the same oracle must then fail.

The `manby-parity` job in `.github/workflows/evals.yml` runs on every PR and push
to main. It builds the Tippecanoe reference from the pinned commit with
`scripts/ci/install-tippecanoe.sh`; upstream did not tag 2.82.0. It then installs
the manby release with `scripts/ci/install-manby.sh`, which checks the pinned
SHA-256 and that `manby --version` names the same Tippecanoe release. The test
step fails if either variable is missing. Upgrading either tool means changing
both pins together and rerunning this job.

To reproduce the job locally on Linux x86_64 (a C++ toolchain plus SQLite and
zlib headers are needed for the reference build):

```bash
python3 -m pip install -r evals/requirements-tylertoo.txt
dir="$(mktemp -d)"
bash scripts/ci/install-tippecanoe.sh "$dir/tippecanoe"
bash scripts/ci/install-manby.sh "$dir/manby/manby"
OMS_TIPPECANOE="$dir/tippecanoe/tippecanoe" OMS_MANBY="$dir/manby/manby" \
  python3 -m unittest tests.test_manby -v
```

Ordinary unit discovery without both variables skips these tests. Test
execution never installs or fetches anything.

## Evidence behind the guidance

A one-off comparison on 2026-11-24 used manby 0.2.10 and Tippecanoe 2.82.0 in
one container on an 8-core x86_64 host. The input was an OSM Estonia extract
(about 426k POIs, 351k roads, 905k buildings, 185k landcover polygons) plus 8M
synthetic points. Eleven cases covered density dropping and coalescing,
clustering, multiple layers with exclusions/filters/type coercion, parallel
reads, FlatGeobuf and GeoParquet input, `tile-join` and a memory budget. About
158,000 tiles were compared, and every decompressed tile and all tileset
metadata matched. Error messages and exit codes matched for unknown options,
missing or malformed input, invalid geometry, existing output and oversized
tiles. Output did not change across reruns or with 1, 3 or 8 threads.

manby was 4.6–22 times faster (median 8.1). Peak memory was lower in 9 cases
and higher in 2 (+7% and +18%). Archives were 1–3% smaller because the
compression differs. With `-s EPSG:3301`, manby's own reprojection differed from
GDAL/PROJ followed by Tippecanoe in 128 of 2,707 building tiles. In dense zoom
9–10 tiles, the same number of features was kept, but up to about 29% of them
were different features. A FlatGeobuf file in EPSG:3301 was not reprojected
without `-s`, while a GeoPackage was. These findings shaped the reprojection and
CRS rules in the guidance.

This is a case study of one host, two releases and one regional dataset. It does
not cover MLT output, remote reads, sharding, manby-only output options, ARM,
macOS or Windows, or inputs larger than RAM. Speed and memory figures are not
guarantees; the guidance therefore asks for measurement on the actual workload.
The project was three weeks old with one main author when evaluated, so
Tippecanoe remains the reference and fallback.
