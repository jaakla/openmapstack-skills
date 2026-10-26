---
schema: openmapstack-findings/v1
project_id: tartu-development-access
question: Identify potentially developable parcels meeting accessibility, education
  catchment (25-minute walking distance to city-owned kindergarten and school), and
  land-use criteria in Tartu, and show them on an interactive map with education POIs
  and catchment areas.
run_id: run-20261025-162537
scope: Tartu linn land screening using pinned source snapshots captured 2026-10-25
validation:
  status: warning
  checks:
  - id: geometry_valid
    status: passed
  - id: no_duplicate_cadastral_id
    status: passed
  - id: crs_known
    status: passed
  - id: no_null_cadastral_id
    status: passed
  - id: row_count_gt_zero
    status: passed
  - id: parcel_area_range
    status: passed
  - id: highway_distance_check
    status: passed
  - id: source_semantics_verified
    status: passed
  - id: education_ownership_check
    status: passed
  - id: source_result_complete
    status: passed
  - id: overrides_applied
    status: passed
  - id: manifest_graph_resolves
    status: passed
  - id: view_controls_match_pipeline
    status: passed
  - id: qgis_project_static_valid
    status: passed
  - id: qgis_runtime_load
    status: not_testable
  - id: manifest_report_parity
    status: passed
  - id: education_source_license
    status: warning
  - id: education_access_method
    status: passed
validation_report: validation/latest-report.json
context_sha256: sha256:3c41d699d705b3e8885740c9be9b3194aa0bafba88bbb27e77bd2ff1ebd60847
assumptions:
- id: A1
  statement: '"Near a main road" is interpreted as <= 2000 m planar distance to a
    national primary (Põhimaantee) or secondary (Tugimaantee) road or hypothetical
    scenario connector.'
  rationale: Standard arterial road access threshold for regional land-use development.
- id: A2
  statement: Parcel area is measured in EPSG:3301 (L-EST97).
  rationale: Metric area calculation requires a projected national CRS.
- id: A3
  statement: Education accessibility uses reverse Valhalla pedestrian isochrones on
    a pinned OSM network, at 4.8 km/h, for 15, 20, 25, 30 and 40 minutes. The accepted
    threshold is 25 minutes.
  rationale: Reverse expansion models walking to the facility. Contours approximate
    network reachability; they do not supply an exact parcel travel time. OSM access,
    crossings and barriers determine the graph.
- id: A4
  statement: Road distance is measured from the nearest parcel edge. Education accessibility
    requires a positive-area intersection between the parcel and a facility's network
    isochrone.
  rationale: This is land screening, not a route from a verified building entrance.
    Large parcels may intersect a catchment without having a usable entrance there;
    internal paths and access rights require verification.
warnings:
- id: SCENARIO-001
  severity: high
  layer: education_pois, planned_roads
  issue: scenario_in_effect
  statement: The headline numbers include two hypothetical overrides — OVERRIDE-001
    (Ilmatsalu kindergarten treated as not operating) and OVERRIDE-002 (connector
    road that does not exist). They are not a description of present-day conditions.
  mitigation: Remove both overrides from project.yaml and rerun for the authoritative
    baseline; every scenario feature is styled distinctly and badged in the map view.
- id: DATA-001
  severity: medium
  layer: education_pois
  issue: completeness_unknown
  statement: The municipal education ArcGIS items do not publish explicit license
    text.
  mitigation: Confirm reuse terms with Tartu City Government before redistribution.
- id: METHOD-001
  severity: medium
  layer: education_catchments
  issue: network_model_limitations
  statement: Network catchments depend on OSM paths, crossings and access tags. Polygon
    contours approximate reachability; parcel overlap and snapped facility points
    do not establish legal entrances. The scenario connector is not part of the walking
    graph.
  mitigation: Verify entrances, internal access and mapped barriers before consequential
    decisions. The first sampled contour is not an exact route duration.
findings:
- id: screened_parcels_and_education_tiers
  statement: 518 parcels meet the accepted land-use, Tartu linn, minimum 20,000 m²
    area and maximum 2,000 m planar road-distance criteria. At the 25-minute pedestrian
    contour threshold, 57 intersect both school and kindergarten catchments (Tier
    1), 40 intersect one type (Tier 2), and 421 intersect neither (Tier 3).
  evidence:
  - candidate_parcels_geojson
  - candidate_parcels_parquet
  - candidate_parcels_gpkg
  - education_catchments_geojson
  limitations:
  - Catchment membership means positive-area parcel intersection with a modelled contour,
    not a verified entrance or exact journey time. First intersecting sampled contours
    (15/20/25/30/40 minutes) are not continuous travel-time estimates. OSM completeness,
    snapping and unsurveyed entrances limit the result.
- id: hypothetical_road_dependency
  statement: 35 of the 518 accepted parcels are more than 2,000 m from an official
    main road but within that distance of the hypothetical connector; their road-distance
    eligibility depends on OVERRIDE-002.
  evidence:
  - candidate_parcels_geojson
  - candidate_parcels_parquet
  - candidate_parcels_gpkg
  - main_roads_geojson
  limitations:
  - The connector is a user-supplied hypothetical scenario, not an official or approved
    road. It affects planar proximity only and is not inserted into the pedestrian
    routing graph. This count is restricted to accepted parcels, not a separate complete
    baseline run.
- id: kindergarten_scenario_effect
  statement: 32 accepted parcels intersect a baseline 25-minute kindergarten catchment
    but no effective kindergarten catchment at that threshold after the Ilmatsalu
    kindergarten is switched off in OVERRIDE-001.
  evidence:
  - candidate_parcels_geojson
  - candidate_parcels_parquet
  - candidate_parcels_gpkg
  - education_pois_geojson
  - education_catchment_variants_geojson
  limitations:
  - Switching off the facility is a hypothetical analytical scenario, not a claim
    that it has closed. The municipal education source has no stated license. Replayed
    source snapshots establish these historical model results; present-day availability,
    access, legal development rights and source freshness are not verified.
evidence:
  candidate_parcels_geojson:
    definition:
      path: data/derived/final-candidates.json
      format: GeoJSON (EPSG:4326)
      generated_by: multi_criteria_accessibility
    files:
    - path: data/derived/final-candidates.json
      sha256: sha256:152b1650ac5bfe19a3b5e388ad34c317e4b241c6b2c2a996d55e39f262c3929b
  candidate_parcels_parquet:
    definition:
      path: data/derived/final-candidates.parquet
      format: GeoParquet (EPSG:3301)
      generated_by: multi_criteria_accessibility
    files:
    - path: data/derived/final-candidates.parquet
      sha256: sha256:a91d3049c7e6a318b3a6ecae6e5c95f7278d402eccdb777bff8841ec1c1d438d
  candidate_parcels_gpkg:
    definition:
      path: data/derived/final-candidates.gpkg
      format: GeoPackage (EPSG:3301)
      generated_by: multi_criteria_accessibility
    files:
    - path: data/derived/final-candidates.gpkg
      sha256: sha256:267112bfe36dde8aa09517886bd086864b4f1531184903bb9cc823ef6a0b34ad
  education_catchments_geojson:
    definition:
      path: data/derived/education_catchments.json
      format: GeoJSON (EPSG:4326)
      generated_by: calculate_education_catchments
    files:
    - path: data/derived/education_catchments.json
      sha256: sha256:e094b356be60bcf5ca6b018db276bcce792f0dc9ada33e31b8af8e192c6c1544
  main_roads_geojson:
    definition:
      path: data/derived/main_roads.json
      format: GeoJSON (EPSG:4326)
      generated_by: load_roads
    files:
    - path: data/derived/main_roads.json
      sha256: sha256:34da08901c1384b6872ccae7b096b300f640c9a60270df2da060cbfdcff36d8f
  education_pois_geojson:
    definition:
      path: data/derived/education_pois.json
      format: GeoJSON (EPSG:4326)
      generated_by: apply_education_override
    files:
    - path: data/derived/education_pois.json
      sha256: sha256:b84e2f776811c380f8f4df3a3d84f78af85af4c7138dccfa7dd8a749d6fc5917
  education_catchment_variants_geojson:
    definition:
      path: data/derived/education_catchment_variants.json
      format: GeoJSON (EPSG:4326)
      generated_by: calculate_education_catchments
      role: exploratory_companion
      note: Precomputed walking catchments at every offered time threshold, for effective
        and baseline facility sets. The canonical pair remains education_catchments_geojson.
    files:
    - path: data/derived/education_catchment_variants.json
      sha256: sha256:1efbec5448718906d791576b92e75f0f1a2464c0a068ae8a9e096e45acd8bf83
---
# Findings

Identify potentially developable parcels meeting accessibility, education catchment (25-minute walking distance to city-owned kindergarten and school), and land-use criteria in Tartu, and show them on an interactive map with education POIs and catchment areas.

Scope: Tartu linn land screening using pinned source snapshots captured 2026-10-25. Run: `run-20261025-162537`. Validation: **warning**.

## screened_parcels_and_education_tiers

518 parcels meet the accepted land-use, Tartu linn, minimum 20,000 m² area and maximum 2,000 m planar road-distance criteria. At the 25-minute pedestrian contour threshold, 57 intersect both school and kindergarten catchments (Tier 1), 40 intersect one type (Tier 2), and 421 intersect neither (Tier 3).

Evidence:

- [candidate_parcels_geojson](data/derived/final-candidates.json)
- [candidate_parcels_parquet](data/derived/final-candidates.parquet)
- [candidate_parcels_gpkg](data/derived/final-candidates.gpkg)
- [education_catchments_geojson](data/derived/education_catchments.json)

Limitation: Catchment membership means positive-area parcel intersection with a modelled contour, not a verified entrance or exact journey time. First intersecting sampled contours (15/20/25/30/40 minutes) are not continuous travel-time estimates. OSM completeness, snapping and unsurveyed entrances limit the result.

## hypothetical_road_dependency

35 of the 518 accepted parcels are more than 2,000 m from an official main road but within that distance of the hypothetical connector; their road-distance eligibility depends on OVERRIDE-002.

Evidence:

- [candidate_parcels_geojson](data/derived/final-candidates.json)
- [candidate_parcels_parquet](data/derived/final-candidates.parquet)
- [candidate_parcels_gpkg](data/derived/final-candidates.gpkg)
- [main_roads_geojson](data/derived/main_roads.json)

Limitation: The connector is a user-supplied hypothetical scenario, not an official or approved road. It affects planar proximity only and is not inserted into the pedestrian routing graph. This count is restricted to accepted parcels, not a separate complete baseline run.

## kindergarten_scenario_effect

32 accepted parcels intersect a baseline 25-minute kindergarten catchment but no effective kindergarten catchment at that threshold after the Ilmatsalu kindergarten is switched off in OVERRIDE-001.

Evidence:

- [candidate_parcels_geojson](data/derived/final-candidates.json)
- [candidate_parcels_parquet](data/derived/final-candidates.parquet)
- [candidate_parcels_gpkg](data/derived/final-candidates.gpkg)
- [education_pois_geojson](data/derived/education_pois.json)
- [education_catchment_variants_geojson](data/derived/education_catchment_variants.json)

Limitation: Switching off the facility is a hypothetical analytical scenario, not a claim that it has closed. The municipal education source has no stated license. Replayed source snapshots establish these historical model results; present-day availability, access, legal development rights and source freshness are not verified.

## Assumptions and limitations

- "Near a main road" is interpreted as <= 2000 m planar distance to a national primary (Põhimaantee) or secondary (Tugimaantee) road or hypothetical scenario connector. Standard arterial road access threshold for regional land-use development.
- Parcel area is measured in EPSG:3301 (L-EST97). Metric area calculation requires a projected national CRS.
- Education accessibility uses reverse Valhalla pedestrian isochrones on a pinned OSM network, at 4.8 km/h, for 15, 20, 25, 30 and 40 minutes. The accepted threshold is 25 minutes. Reverse expansion models walking to the facility. Contours approximate network reachability; they do not supply an exact parcel travel time. OSM access, crossings and barriers determine the graph.
- Road distance is measured from the nearest parcel edge. Education accessibility requires a positive-area intersection between the parcel and a facility's network isochrone. This is land screening, not a route from a verified building entrance. Large parcels may intersect a catchment without having a usable entrance there; internal paths and access rights require verification.
- The headline numbers include two hypothetical overrides — OVERRIDE-001 (Ilmatsalu kindergarten treated as not operating) and OVERRIDE-002 (connector road that does not exist). They are not a description of present-day conditions.
- The municipal education ArcGIS items do not publish explicit license text.
- Network catchments depend on OSM paths, crossings and access tags. Polygon contours approximate reachability; parcel overlap and snapped facility points do not establish legal entrances. The scenario connector is not part of the walking graph.

[Project, sources and definitions](project.yaml)
 · [Validation report](validation/latest-report.json)
