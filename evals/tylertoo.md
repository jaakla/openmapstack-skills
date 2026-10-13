# Tylertoo delivery review

The shared [web-delivery guidance](../skills/open-map-stack/references/web-delivery.md#tylertoo--geoparquet-native-vector-tiles)
adds a tool choice, not a new project contract. These focused review scenarios
cover that choice without extending the generic routing benchmark infrastructure.
Case `026-tiler-selection` now makes the local native writer, no-thinning cells,
and retained Tippecanoe workflow decisions runnable in fixture and live modes.
It asks for bounded argv plans and grades their tool/input/options semantically,
not by prose or token presence. Mutations `947`–`949` require rejection of the
wrong writer, a missing coverage safeguard and an unwanted tool migration,
each against a healthy control. This is planning coverage, not evidence of
successful execution or map appearance. The remaining remote/sharding scenarios
below are reviewer prompts, not automated claims.

```bash
python3 evals/run.py --mode fixture --case 026-tiler-selection \
  --case 947-tiler-wrong-tool --case 948-tiler-thinning \
  --case 949-tiler-replace-existing
```

The fixture controls and a stub live adapter test the grader without model
calls. Actual live-agent runs remain subject to the explicit model/budget policy.

| Prompt | Acceptance evidence | Failure to flag |
|---|---|---|
| Publish this local GeoParquet catalog layer as a static map preview. | Consider direct tylertoo conversion; pin the tested runtime and source; inspect archive metadata and rendered zooms; preserve source attribution. | Unnecessary GeoJSON intermediate presented as mandatory, or tiles replacing analytical source data. |
| Tile just this AOI from remote GeoParquet with a tight memory budget. | Verify remote input/CRS support, row-group pruning and bounded-memory/spill settings; apply an exact spatial predicate if required. | Full-download promise disguised as range reads, bbox treated as exact clipping, or unmeasured speed/memory guarantees. |
| Show every parcel in this choropleth, including at coarse zooms. | Investigate thinning; test verbatim or tuned settings against source coverage and tile size at low/middle/high zooms. | Default thinning silently removes classes or cells; display geometry used for area totals. |
| Keep our tuned Tippecanoe GeoJSON stream and zoom filters working. | Preserve the existing tool unless an evidenced migration meets the same behavior. | Blind replacement with tylertoo or copied incompatible flags. |
| Build a planet OSM basemap; alternatively distribute a huge GeoParquet field overlay. | Distinguish Planetiler basemap profiles from tylertoo overlay sharding; for shards verify common plans, disjoint ownership and coarse-zoom coverage. | Generic overlapping PMTiles merge treated as a complete sharded build. |

For a future agent trial, supply the actual requested input and task only; keep
this rubric with the reviewer. Retain commands, version, source identities,
archive inspection and screenshots. Follow `AGENTS.md` model/budget authorization
before live calls. No live-agent adherence claim follows from the tool test below.

## Executable local integration check

`tests/test_tylertoo.py` writes two synthetic adjoining GeoParquet polygons,
executes both direct tiling and overview/validate/export, then independently
decodes the PMTiles using `pmtiles` and `mapbox-vector-tile`. It checks both
polygons at both requested zooms, source-layer name, stable feature IDs,
attribute values and exclusion of an unwanted property. A missing-polygon
mutation must fail the same oracle. These small checks do not prove browser
appearance, remote I/O efficiency, distributed completeness or performance.

The `tylertoo-integration` job in `.github/workflows/evals.yml` runs on every PR
and push to main. It installs Python dependencies from
`evals/requirements-tylertoo.txt`, downloads upstream v0.8.0 using
`scripts/ci/install-tylertoo.sh`, verifies the pinned SHA-256 and reported version,
and exports `OMS_TYLERTOO` through `GITHUB_ENV` before executing both real-tool tests.
The test step fails if that variable is missing.
Installation/dependency errors fail the job; CI needs no manual preinstall or
variable setup. The separate fixture job also runs the planning cases and
mutation controls, including in its network-disabled container.

To reproduce the integration job locally on Linux x86_64 in a Python environment:

```bash
python3 -m pip install -r evals/requirements-tylertoo.txt
export OMS_TYLERTOO="$(mktemp -d)/tylertoo"
bash scripts/ci/install-tylertoo.sh "$OMS_TYLERTOO"
python3 -m unittest tests.test_tylertoo -v
python3 -m unittest tests.test_collection tests.evals.test_tiling -v
python3 scripts/sync_skill_assets.py --check
```

Ordinary local unit discovery without `OMS_TYLERTOO` skips the external-tool
tests; the dedicated CI job always sets it. Test execution never installs or
fetches anything. The committed installer is Linux x86_64-specific; other
platforms can provide a verified executable through the same variable.
