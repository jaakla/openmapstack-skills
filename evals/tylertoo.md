# Tylertoo delivery review

The shared [web-delivery guidance](../skills/open-map-stack/references/web-delivery.md#tylertoo--geoparquet-native-vector-tiles)
adds a tool choice, not a new project contract. These focused review scenarios
cover that choice without extending the generic routing benchmark infrastructure.
They are manual behavioral evals, not scored cases in `evals/run.py`.

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

Install a verified tylertoo release using upstream instructions, plus test-only
Python dependencies `pyarrow`, `pmtiles`, and `mapbox-vector-tile`. Then run:

```bash
OMS_TYLERTOO=/absolute/path/to/tylertoo python3 -m unittest tests.test_tylertoo -v
python3 -m unittest tests.test_collection -v
python3 scripts/sync_skill_assets.py --check
```

Without `OMS_TYLERTOO`, runtime tests explicitly skip. With it, missing dependencies,
unsupported flags, failed commands and incorrect artifacts fail; nothing is
installed or fetched by the test. The integration check was exercised against
upstream v0.8.0; rerun against the release selected for a real project.
