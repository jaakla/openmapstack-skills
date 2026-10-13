Prepare a reviewable tiling plan for three jobs; do not execute tools or download
anything. Write `tiling-plan.json` with keys `preview`, `coverage`, and `existing`,
each containing one argv array (executable followed by individual arguments).
This task needs no full project scaffold. Use bare executable names, explicit
long option names, explicit `tiles` for tylertoo, and no shell wrappers. Include
only input/output, min/max zoom, layer name, the existing filter where requested,
and any necessary switch to disable generalization. Do not add version checks or
inspection commands to these arrays; those belong to later execution QA.

- `preview`: publish local `events.parquet` (valid WGS84 GeoParquet) directly to
  `events.pmtiles`, layer `events`, zooms 4–14. We want a GeoParquet-native writer
  without a format-conversion intermediate and accept default generalization.
- `coverage`: publish already aggregated WGS84 GeoParquet `cells.parquet` to
  `cells.pmtiles`, layer `cells`, zooms 4–8 with the same native writer. Preserve
  every cell without further simplification, thinning, density reduction or a
  tile-size cap. The cells are small enough for this task's output budget.
- `existing`: retain our established Tippecanoe workflow for `cities.geojson`
  producing `cities.pmtiles`, layer `cities`, zooms 0–10, with this unchanged
  feature filter: `{"*": [">", "population", 10000]}`. No tool migration is requested.
