---
schema: openmapstack-findings/v1
project_id: nyc-private-mobility
question: Identify promising NYC areas for a new operations/charging hub for tenant
  alpha, using current fleet and hub coverage and account demand, and show ranked
  candidate zones on an interactive map while respecting all database access restrictions.
run_id: run-20261016-145542
scope: pinned tenant-alpha synthetic business snapshots on the NYC H3 resolution-8
  study grid
validation:
  status: passed
  checks:
  - id: h3_grid_valid
    status: passed
  - id: h3_references_consistent
    status: passed
  - id: geometry_valid
    status: passed
  - id: crs_known
    status: passed
  - id: row_count_gt_zero
    status: passed
  - id: no_null_zone_id
    status: passed
  - id: rls_scope_alpha_only
    status: passed
  - id: protected_columns_absent
    status: passed
  - id: score_components_complete
    status: passed
  - id: score_range
    status: passed
  - id: eligibility_thresholds
    status: passed
  - id: fleet_latest_observation
    status: passed
  - id: qgis_project_static_valid
    status: passed
validation_report: validation/latest-report.json
context_sha256: sha256:3ec18714b0763fd87fa75db2f449fa13780649cb74ab5233dc9fd3e240db2c66
assumptions:
- id: A1
  statement: Business observations are synthetic demo data captured from live services.
    Some synthetic fleet point locations reuse actual 2016 NYC TLC trip pickup coordinates;
    they are not tracked vehicles.
  rationale: The PostGIS fleet seed generates vehicle IDs, statuses and 2026 timestamps
    for 281 pinned TLC pickup coordinates. The coordinates are historical public trip
    data, not current fleet evidence.
- id: A2
  statement: Demand is the number of reader-visible tenant-alpha BigQuery trip pickups
    spatially contained in each PostGIS H3 cell, over the dates present in the captured
    trip table. Peak day, variability, active days and mean distance are retained.
  rationale: The live BigQuery table retains legacy source zones. Point-based aggregation
    avoids claiming those rectangular zones are H3 cells; trips outside the study
    grid are excluded.
- id: A3
  statement: Distance to the closest existing hub is measured from the zone centroid
    in EPSG:32618 (UTM 18N, metres).
  rationale: A local metric CRS for NYC; centroid-level screening is appropriate for
    zone-level siting.
- id: A4
  statement: Market context combines MotherDuck source-zone scores attributed by H3
    cell centre through BigQuery reference polygons with POIs counted directly inside
    H3 cells.
  rationale: Every H3 centre must match exactly one reference polygon and a reader-visible
    score. POI counts and raw market score are stored in zone-metrics.parquet.
- id: A5
  statement: PostGIS supplies genuine H3 resolution-8 geometries for a land-centred
    study grid. Integer zone IDs are compatibility aliases, not NYC TLC identifiers.
  rationale: The PostGIS seed derives polygon geometry from pinned H3 cell IDs using
    h3-pg functions; the live reader capture is the analysis input.
- id: A6
  statement: Fleet presence counts each synthetic vehicle once using its latest recorded_at
    observation. The expanded demo seed includes 281 synthetic tenant-alpha vehicles
    located at pinned 2016 TLC pickup coordinates.
  rationale: The public coordinates are location seeds only. No TLC vehicle identity
    or live telemetry is represented; position_id breaks timestamp ties.
- id: A7
  statement: The three provisioned services contain seeded synthetic business data.
    TLC 2016 pickup coordinates were separately captured as historical public source
    geography and reused to enrich the synthetic PostGIS fleet seed.
  rationale: The analysis uses the reader-visible PostGIS fleet capture after the
    enrichment; the original TLC sample and its source hash remain pinned for provenance.
warnings: []
findings:
- id: eligible_hub_cells
  statement: '6 of 83 studied H3 cells meet all screening thresholds: at least 30
    trips, at least 1500 m from an existing hub, and at most 6 latest observed vehicles.'
  evidence:
  - hub_candidates_geojson
  - hub_candidates_parquet
  - zone_metrics_geojson
  limitations:
  - Synthetic business records; these are screening cells, not verified sites or investment
    recommendations. Hub distances are centroid-to-hub straight-line distances in
    EPSG:32618, not driving distances.
- id: highest_scoring_cell
  statement: The highest-scoring eligible cell is 882a100d1bfffff (Brooklyn), with
    a score of 85.60/100, 32 trips, 2417 m to the nearest hub and 0 latest observed
    vehicles.
  evidence:
  - hub_candidates_geojson
  - hub_candidates_parquet
  limitations:
  - The score is the declared weighted demo model, not a probability of success. A
    latest observation does not establish current vehicle availability.
- id: demand_within_study_grid
  statement: The studied grid contains 2090 captured trip events across 83 cells.
  evidence:
  - zone_metrics_geojson
  - zone_metrics_parquet
  limitations:
  - Counts cover the pinned reader-visible business snapshots within this grid, not
    all NYC travel demand. Historical 2016 TLC pickup coordinates place some synthetic
    fleet points; they are not live tracking. Warehouse permission enforcement and
    present-day market suitability are not verified by this replay.
evidence:
  hub_candidates_geojson:
    definition:
      path: data/derived/hub-candidates.geojson
      format: GeoJSON (EPSG:4326)
      generated_by: export_candidates
    files:
    - path: data/derived/hub-candidates.geojson
      sha256: sha256:7197362228c912ddd7b9be77a3baecbd9c4fa212439d0005d6360077b2675210
  hub_candidates_parquet:
    definition:
      path: data/derived/hub-candidates.parquet
      format: GeoParquet (EPSG:4326)
      generated_by: export_candidates
    files:
    - path: data/derived/hub-candidates.parquet
      sha256: sha256:d41f27ad236c0e007c9cb2a8128512310da1aa41ac360192cef01b5c09db071d
  zone_metrics_geojson:
    definition:
      path: data/derived/zone-metrics.geojson
      format: GeoJSON (EPSG:4326)
      generated_by: combine_metrics
    files:
    - path: data/derived/zone-metrics.geojson
      sha256: sha256:15d1cdc1cd75ac1869ffb5caf9cd188f72ae85a34a9af652e21ee17e41bdb286
  zone_metrics_parquet:
    definition:
      path: data/derived/zone-metrics.parquet
      format: GeoParquet (EPSG:4326)
      generated_by: combine_metrics
    files:
    - path: data/derived/zone-metrics.parquet
      sha256: sha256:9681185017fb0ab4de09d88c4295544db507c284f36b7600b3bd8a03eedeec62
---
# Findings

Identify promising NYC areas for a new operations/charging hub for tenant alpha, using current fleet and hub coverage and account demand, and show ranked candidate zones on an interactive map while respecting all database access restrictions.

Scope: pinned tenant-alpha synthetic business snapshots on the NYC H3 resolution-8 study grid. Run: `run-20261016-145542`. Validation: **passed**.

## eligible_hub_cells

6 of 83 studied H3 cells meet all screening thresholds: at least 30 trips, at least 1500 m from an existing hub, and at most 6 latest observed vehicles.

Evidence:

- [hub_candidates_geojson](data/derived/hub-candidates.geojson)
- [hub_candidates_parquet](data/derived/hub-candidates.parquet)
- [zone_metrics_geojson](data/derived/zone-metrics.geojson)

Limitation: Synthetic business records; these are screening cells, not verified sites or investment recommendations. Hub distances are centroid-to-hub straight-line distances in EPSG:32618, not driving distances.

## highest_scoring_cell

The highest-scoring eligible cell is 882a100d1bfffff (Brooklyn), with a score of 85.60/100, 32 trips, 2417 m to the nearest hub and 0 latest observed vehicles.

Evidence:

- [hub_candidates_geojson](data/derived/hub-candidates.geojson)
- [hub_candidates_parquet](data/derived/hub-candidates.parquet)

Limitation: The score is the declared weighted demo model, not a probability of success. A latest observation does not establish current vehicle availability.

## demand_within_study_grid

The studied grid contains 2090 captured trip events across 83 cells.

Evidence:

- [zone_metrics_geojson](data/derived/zone-metrics.geojson)
- [zone_metrics_parquet](data/derived/zone-metrics.parquet)

Limitation: Counts cover the pinned reader-visible business snapshots within this grid, not all NYC travel demand. Historical 2016 TLC pickup coordinates place some synthetic fleet points; they are not live tracking. Warehouse permission enforcement and present-day market suitability are not verified by this replay.

## Assumptions and limitations

- Business observations are synthetic demo data captured from live services. Some synthetic fleet point locations reuse actual 2016 NYC TLC trip pickup coordinates; they are not tracked vehicles. The PostGIS fleet seed generates vehicle IDs, statuses and 2026 timestamps for 281 pinned TLC pickup coordinates. The coordinates are historical public trip data, not current fleet evidence.
- Demand is the number of reader-visible tenant-alpha BigQuery trip pickups spatially contained in each PostGIS H3 cell, over the dates present in the captured trip table. Peak day, variability, active days and mean distance are retained. The live BigQuery table retains legacy source zones. Point-based aggregation avoids claiming those rectangular zones are H3 cells; trips outside the study grid are excluded.
- Distance to the closest existing hub is measured from the zone centroid in EPSG:32618 (UTM 18N, metres). A local metric CRS for NYC; centroid-level screening is appropriate for zone-level siting.
- Market context combines MotherDuck source-zone scores attributed by H3 cell centre through BigQuery reference polygons with POIs counted directly inside H3 cells. Every H3 centre must match exactly one reference polygon and a reader-visible score. POI counts and raw market score are stored in zone-metrics.parquet.
- PostGIS supplies genuine H3 resolution-8 geometries for a land-centred study grid. Integer zone IDs are compatibility aliases, not NYC TLC identifiers. The PostGIS seed derives polygon geometry from pinned H3 cell IDs using h3-pg functions; the live reader capture is the analysis input.
- Fleet presence counts each synthetic vehicle once using its latest recorded_at observation. The expanded demo seed includes 281 synthetic tenant-alpha vehicles located at pinned 2016 TLC pickup coordinates. The public coordinates are location seeds only. No TLC vehicle identity or live telemetry is represented; position_id breaks timestamp ties.
- The three provisioned services contain seeded synthetic business data. TLC 2016 pickup coordinates were separately captured as historical public source geography and reused to enrich the synthetic PostGIS fleet seed. The analysis uses the reader-visible PostGIS fleet capture after the enrichment; the original TLC sample and its source hash remain pinned for provenance.

[Project, sources and definitions](project.yaml)
 · [Validation report](validation/latest-report.json)
