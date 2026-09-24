# Accessibility screen for candidate parcels

Use the supplied parcel, road, and POI layers in `data/source/` to find parcels that could support the proposed use. Include parcels that are at least 8,000 square metres, have zoning `ARIMAA`, `MAATULUNDUSMAA`, or `TOOTMISMAA`, and are within 2,000 metres of the main road.


Python 3, DuckDB Spatial and the openmapstack package are installed; use `openmapstack` or `python3 -m openmapstack` for the CLI. Do not assume other geospatial Python packages, and do not install packages.

Deliver a complete openmapstack-project/v1 project in this directory. The frozen inputs are already in `data/source/`; keep them byte-for-byte unchanged. Include project.yaml, a canonical executable pipeline, validation evidence, project.qgz and dashboard.html. Keep the project rerunnable without this conversation.

Artifact interface (required delivery names, not expected analytical answers):
Write the candidate output below, even when it is empty. Preserve original parcel IDs.
Store real geometry and CRS metadata; do not write unlabelled WKB bytes as spatial Parquet.
Execute the canonical pipeline and retain machine-readable checks with honest evidence and
input/output hashes, a matching run record and project status. A report must include every
check declared in project.yaml; unavailable capability must remain explicit. Do not invent
missing attributes or change the stated selection rules to obtain a nonempty result.
The numeric evidence fields below belong directly on the corresponding report checks and
refer to the candidate dataset. Document the parcel-selection predicate on the named source.
QGIS must use portable relative datasources in formats every QGIS build reads (GeoPackage,
GeoJSON or FlatGeobuf, not Parquet), valid styles, complete layer CRS definitions that
match each layer's data,
enabled reprojection and groups matching the manifest. The dashboard must reflect the same
layers, parameters and warnings. Include the declared analysis/user_overrides groups even
when there are no user edits. The delivered project must survive a clean rerun after relocation.

```yaml
project_schema: openmapstack-project/v1
files:
- project.yaml
- pipeline.py
- validation/latest-report.json
- project.qgz
- dashboard.html
unchanged_inputs:
- data/source/parcels.geojson
- data/source/roads.geojson
- data/source/pois.geojson
candidate:
  path: data/derived/candidate-parcels.parquet
  format: GeoParquet
  crs: EPSG:3301
  id_field: cadastral_id
parcel_source_id: cadastral_parcels
validation_evidence:
- id: geometry_valid
  numeric_fields:
  - features_checked
  - invalid_count
- id: no_duplicate_cadastral_id
  numeric_fields:
  - duplicates
- id: no_null_cadastral_id
  numeric_fields:
  - nulls
layer_groups:
- analysis
- user_overrides
```
