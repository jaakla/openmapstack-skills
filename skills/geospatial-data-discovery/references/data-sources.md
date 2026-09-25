# Data Sources

Where to look for open geospatial data, and how to verify what you find. Discovery comes before download; STAC is the modern catalog protocol for raster, and Overture's STAC + GeoParquet pattern increasingly applies to vector basemaps too.

This file lists entry points and methods, not dataset internals. File formats, layer and field names, code lists, record counts, download packaging, server limits and licenses change without notice, so this guide deliberately does not record them. Read them from the provider's current pages, catalog metadata and service capabilities when you use a source, record what you saw and when, and look for further datasets in the same catalogs.

## Discovery hierarchy — try in this order

1. **Existing STAC catalogs** — for any raster, satellite, or EO data
2. **A Portolan catalog**, when the user names one or points at a catalog root — a static STAC catalog whose datasets are already cloud-native and self-documenting
3. **Overture Maps** — for global building, place, transportation, address basemap
4. **OpenStreetMap (via Overpass or extracts)** — for detailed local features Overture doesn't cover
5. **National / regional portals and SDI catalogs** — for authoritative or jurisdiction-specific data
6. **Specialist datasets** — building footprints, elevation, point clouds, weather/climate, population, land cover

Only fall back to ad-hoc downloads when the above don't cover the need.

## Verify a source before relying on it

For each candidate, read these at the time of use, in roughly this order:

1. **The catalog record** — an SDI/INSPIRE metadata record (CSW, GeoNetwork), a STAC collection, a Portolan `collection.json`, or a portal dataset page. It names the owner, update cycle, coverage, access points and license.
2. **The access point itself** — the download page for current packaging and formats; for services, `GetCapabilities`, `DescribeFeatureType`, or an OGC API landing page with `/collections` and `/queryables`. Take layer names, fields and CRSs from here, never from memory or an old example.
3. **The provider's license or attribution page** — licenses differ per dataset, per theme and sometimes per region. Link the exact page you read.
4. **The data** — after retrieval, inspect the actual schema, code lists, extent and feature count before filtering or joining.

Rules that follow from this:

* Type codes and registry-link fields are not filters for "real" features. A subtype code is not a universal “real building” predicate, and a registry linkage is not proof that a feature exists. Read the current code list and field definitions, apply the population the user asked for, and disclose any exclusion.
* Do not claim lineage between datasets, for example that one is derived from another, unless a source you read documents it.
* If current metadata cannot be retrieved, say so; do not present remembered details as verified.

## STAC — SpatioTemporal Asset Catalog

The default protocol for raster discovery. Every major satellite imagery provider now exposes a STAC API. [STAC Index](https://stacindex.org/) lists public catalogs beyond these.

### Primary STAC endpoints

| Catalog | URL | Coverage |
|---|---|---|
| Microsoft Planetary Computer | `https://planetarycomputer.microsoft.com/api/stac/v1` | Sentinel, Landsat, MODIS, NAIP, climate, DEMs — broadest |
| Element 84 Earth Search | `https://earth-search.aws.element84.com/v1` | Sentinel-2 on AWS |
| Copernicus Data Space | `https://catalogue.dataspace.copernicus.eu/stac` | Official Sentinel access |
| USGS LandsatLook | `https://landsatlook.usgs.gov/stac-server` | Landsat archive |
| Overture Maps | `https://labs.overturemaps.org/stac/catalog.json` | Vector basemap themes |

Read a collection's current bands, assets and item properties from the catalog rather than assuming them.

### Search pattern (Python)

```python
from pystac_client import Client
import planetary_computer  # for MS PC, signs asset URLs

client = Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace,
)
items = client.search(
    collections=["sentinel-2-l2a"],
    bbox=[24.5, 59.3, 25.0, 59.5],   # Tallinn area
    datetime="2025-06-01/2025-08-31",
    query={"eo:cloud_cover": {"lt": 20}},
).item_collection()
```

### Lazy load to xarray (preferred over manual download)

```python
import odc.stac
ds = odc.stac.load(
    items,
    bands=["red", "green", "blue", "nir"],
    chunks={"x": 1024, "y": 1024},  # dask-backed
    resolution=10,
    crs="EPSG:3301",  # reproject during load
)
# Now ds is lazy — only computes when .compute() or .to_zarr() is called
```

`stackstac` is an alternative; `odc-stac` is generally more featureful.

### Cost-aware planning

Estimate the volume before pulling: use `estimate_data_size` (available via STAC MCP), or compute it from the item metadata (bands, resolution, bbox, item count).

## Portolan catalogs

[Portolan](https://portolan-sdi.org/) publishes geospatial data as a **static STAC catalog on object storage** instead of a WMS/WFS/Feature server: vector as GeoParquet paired with PMTiles, raster as COG, tabular as plain Parquet with no geometry column. There is no API to call. You read the JSON, then query the files in place over HTTP range requests — the access pattern this toolkit already defaults to.

**Recognize one by:** a `catalog.json` root served from a bucket, an `AGENTS.md` and `README.md` beside every catalog and collection, and `stac_extensions` carrying a `https://schemas.portolan-sdi.org/portolan/<version>/schema.json` URI. That URI is the only signal of the spec version.

```
catalog-root/
├── catalog.json                 # root STAC Catalog; children via rel: child
├── AGENTS.md                    # linked rel: agents
├── README.md                    # linked rel: describedby
└── {collection_id}/
    ├── collection.json          # extent, providers, license, assets, links
    ├── AGENTS.md, README.md
    ├── {data}.parquet           # asset with role: data
    ├── {data}.pmtiles           # rel: pmtiles link / role: visual
    └── styles/default.json      # asset with role: style + default
```

### Working rules

* **Read the collection's `AGENTS.md` before writing a query.** This is the point of the format: it names the join keys, the CRS, the useful aggregations, and the data-quality traps. Skipping it and inferring the schema from `DESCRIBE` is how you get a plausible wrong answer.
* **Select assets by `roles`, never by asset key.** `data` is the primary Parquet/COG, `visual` the PMTiles, `style` a MapLibre style, `collection-mirror` an `items.parquet` you should query instead of fetching every item JSON.
* **A collection with no `data` asset is not empty — it is partitioned.** Large collections put the files behind a `partition:glob` and/or one item per partition, and the `data` role then sits on the *item*, not the collection. Read the glob or the items; do not conclude the collection has nothing to query. Where the collection publishes an `items.parquet` (`collection-mirror`), query that to find partitions instead of fetching hundreds of item JSONs.
* **Use the `https` href.** An `s3://`/`gs://` URL may appear under `alternate`; do not hand-rewrite one form into the other.
* Query it with the standard DuckDB pattern (`INSTALL spatial; INSTALL httpfs;`) from `spatial-sql.md` — nothing Portolan-specific is required.

### Dedicated skills

`portolan-sdi/portolan-skills` publishes [Agent Skills](https://github.com/anthropics/agent-skills) for this, and they are more detailed than this section: **`reading-portolan`** for consuming a catalog (metadata, assets by role, DuckDB queries, cross-dataset joins, partitioned collections, PMTiles maps), plus publisher-side skills (`portolan-bootstrap`, `portolan-cli`, `portolan-migrate`, `git-backed-catalog`). Prefer them when they are installed; how to install them is agent-specific. `portolan-sdi/portolan-spec` is ground truth when a catalog and any skill disagree, and rule ids such as `PORTO-CORE-027` point into its `requirements.yaml`.

### Pinning a Portolan source

A Portolan collection carries most of what `project-spec.md` requires, so map it across rather than inventing provenance:

| Manifest field | Take from |
|---|---|
| `version.identifier` / `published_at` | collection `updated`, plus the `schemas.portolan-sdi.org` version URI |
| `license` | the SPDX `license` field, or the `rel: license` link when it is `other` |
| provider / authority | `providers` — at least one `producer` and exactly one `host`, host last |
| upstream original | `rel: via` (and `rel: canonical`) on a mirror |

Two traps specific to this mapping:

* **A catalog whose `producer` and `host` differ is a mirror, not the authority.** Its top-level `updated` is the last *sync* time, not the source's publication date. Pin and attribute the original through the `via` link; a mirror can silently lag.
* **`file:checksum` is multihash-encoded, not a raw sha256 string.** Copying it straight into a `sha256:` pin field records a value that will never match the bytes. Decode it, or hash the retrieved file yourself — `local_snapshot` pins are verified against real content.

## Overture Maps — modern open vector basemap

Conflated open data from several sources, released regularly as GeoParquet via a STAC catalog. Entry points: [documentation](https://docs.overturemaps.org/), [release calendar](https://docs.overturemaps.org/release-calendar/), [attribution and licenses](https://docs.overturemaps.org/attribution/). Themes cover addresses, base layers, buildings, administrative divisions, places and transportation; take the current types and columns from the schema reference.

Before writing a direct object-storage path, check the release calendar and use a release still present in the public buckets. Overture keeps only recent public releases. For long-lived pipelines, pin the release and mirror the raw inputs or build an internal archive. Take the current bucket path and partition layout from the documentation.

Query in place rather than downloading (the `overturemaps` CLI also downloads a bbox):

```sql
INSTALL httpfs; LOAD httpfs;
INSTALL spatial; LOAD spatial;

-- OVERTURE_PATH: the current release path and type from the Overture docs.
-- Pin the chosen release in your manifest; do not commit "latest".
SELECT *
FROM read_parquet('OVERTURE_PATH/*.parquet', filename = true, hive_partitioning = 1)
WHERE bbox.xmax >= 24.5 AND bbox.xmin <= 25.0
  AND bbox.ymax >= 59.3 AND bbox.ymin <= 59.5;
```

Use bbox **overlap** as the scan gate so features crossing the area edge are included. For named-area queries, resolve the real boundary first and add an exact spatial predicate such as `ST_Intersects`; a bbox alone is rectangular and will overshoot.

License is per theme and can change between releases: read the attribution page for the release you pin rather than assuming one license for Overture. Preserve the per-feature source provenance Overture publishes.

## OpenStreetMap

Use when Overture doesn't have the feature class needed (footpaths, fine-grained POI tags, niche infrastructure), for very recent edits, or for tag-level richness Overture filters out.

### Choosing the access method

| Need | Tool |
|---|---|
| Small bbox, ad-hoc query | Overpass API |
| Country / region extract | [Geofabrik](https://download.geofabrik.de/), BBBike, NextGIS |
| Whole planet | planet.osm.pbf |
| Iterative refinement, custom filters | `osmium` on a local extract |
| Routable graph for one shot | `osmnx` |

### Overpass via Python

```python
import overpy
api = overpy.Overpass()
result = api.query("""
[out:json][timeout:60];
area["ISO3166-1"="EE"]->.searchArea;
node(area.searchArea)["amenity"="cafe"];
out body;
""")
```

> [!WARNING]
> Public Overpass API instances are rate-limited. For large areas (e.g., country-wide), download an extract instead of slamming the public API.

### Local extract + osmium (for anything serious)

```bash
# Pull a country extract from Geofabrik
wget https://download.geofabrik.de/europe/estonia-latest.osm.pbf

# Filter to POIs
osmium tags-filter estonia-latest.osm.pbf \
  n/amenity=cafe,restaurant,bar \
  -o estonia-food.osm.pbf

# Convert to GeoParquet via ogr2ogr
ogr2ogr -f Parquet estonia-food.parquet estonia-food.osm.pbf points
```

### Load OSM directly to PostGIS

```bash
osm2pgsql -d gisdb --slim -G --hstore -C 4000 \
  -S /usr/share/osm2pgsql/default.style \
  estonia-latest.osm.pbf
```

`--slim` keeps update-able tables; `-G` produces multipolygons; `-C 4000` is RAM cache in MB.

### Administrative boundaries in OSM

`admin_level` meanings differ by country; a generic "city = level 8" query can return nothing. Read the country table on the [OSM wiki](https://wiki.openstreetmap.org/wiki/Tag:boundary%3Dadministrative) before filtering, then query the boundary by its relation ID once you have checked it. Administrative reforms change what a name covers, so check a polygon's area and vintage before treating it as "the city".

## Specialist data sources

Each entry says what the source is and where to start. Check the provider page for current coverage, formats, vintage and license.

### Building footprints

* **Microsoft Global ML Building Footprints** — global, machine-learned footprints: https://github.com/microsoft/GlobalMLBuildingFootprints
* **Google Open Buildings** — footprints for parts of Africa, Asia and Latin America: https://sites.research.google/gr/open-buildings/
* **Overture Buildings** — conflates these with OSM and is usually the simplest entry point.
* **National topographic or cadastral databases** — often the authoritative source within one country (see the regional section).

### Elevation

* **Copernicus DEM** — global DEM; available via STAC (Planetary Computer, [Copernicus Data Space](https://dataspace.copernicus.eu/)).
* **SRTM** — older global DEM.
* **National LiDAR-derived DTMs** — many countries publish them; find them through the national SDI catalog.

### Point clouds

* **USGS 3DEP** — US LiDAR: https://www.usgs.gov/3d-elevation-program
* **OpenTopography** — research repository, global: https://opentopography.org/
* **National open LiDAR** — many EU countries, found through national SDI catalogs.
* Cloud-native point clouds are published as COPC; check what a provider actually offers.

### Weather and Climate

* **Copernicus Climate Data Store** — reanalysis (ERA5) and seasonal forecasts: https://cds.climate.copernicus.eu/
* **ECMWF Open Data** — forecast model output: https://www.ecmwf.int/en/forecasts/datasets/open-data
* **Registry of Open Data on AWS** — NOAA models, radar and many other collections: https://registry.opendata.aws/

### Administrative, population, land cover, and mobility

* **Natural Earth** — small-scale countries, admin boundaries, populated places for overview maps: https://www.naturalearthdata.com/
* **geoBoundaries** — research-grade administrative boundaries: https://www.geoboundaries.org/
* **Overture divisions / OSM boundaries** — practical defaults for admin joins when official boundaries are not required.
* **GHSL / WorldPop** — population grids for exposure and accessibility analysis: https://human-settlement.emergency.copernicus.eu/, https://www.worldpop.org/. Record vintage and resolution.
* **ESA WorldCover / Copernicus Land Monitoring Service** — land cover: https://esa-worldcover.org/, https://land.copernicus.eu/. Record the class schema and year.
* **GTFS feeds** — transit schedules for accessibility and routing; find feeds through the [Mobility Database](https://mobilitydatabase.org/). Terms vary by operator, so record feed URL, download date and terms.
* **Pan-European catalogs** — the [INSPIRE Geoportal](https://inspire-geoportal.ec.europa.eu/) and [data.europa.eu](https://data.europa.eu/) index national datasets and services across the EU.

### Place identifiers and global addressing

Prefer stable identifiers over name-only joins. Store the namespace with the ID (`unlocode`, `geonames`, `wikidata`, `osm`, `wof`, provider-specific place ID) so IDs from different systems cannot be confused.

* **UN/LOCODE** — United Nations code for trade and transport locations; use for ports, airports, terminals, logistics hubs, and shipping/trade analytics.
* **GeoNames ID** — broad global gazetteer identifier for populated places and physical features; useful for coarse global joins and fallback search.
* **Wikidata QID** — cross-domain entity identifier; useful for linking places to external facts, but geometry and admin hierarchy quality varies.
* **OpenStreetMap IDs** — useful for OSM-derived workflows; store element type (`node`, `way`, `relation`) because numeric IDs are not globally unique across types.
* **Who's On First IDs** — useful for place hierarchies and historical/admin boundary context.
* **Provider place IDs** — Google Place IDs, HERE IDs, Mapbox IDs, etc. are service-specific; check storage and reuse terms before persisting them.
* **Open Location Code / Plus Codes** — open, offline-computable global addressing code for places without reliable street addresses. A full code identifies an area, not a parcel or legal address; short codes need a reference locality.
* **Postcodes / ZIP codes** — postal geography is operational, not always polygonal or stable. Use national authoritative datasets where possible; for global coverage consider GeoNames postal codes, OpenAddresses, provider APIs, or paid postal-code datasets.

### OGC services and portals

For WMS/WFS/WMTS/OGC API endpoints, start with `GetCapabilities` or the landing page before guessing layer names. Record service URL, layer ID, CRS, time dimension, paging limit, and terms of use in the manifest.

Use CLI tools like GDAL to process and convert data to GeoParquet (or other suitable file format), instead of expensive direct usage of WMS/WFS/WMTS/OGC API http endpoints. Where a provider offers a bulk download, prefer it over paging a service for whole-region pulls: the files are deterministic and easier to pin.

Paging a WFS to completeness: add a stable `sortBy` on a unique field, loop with `startIndex`, and stop when the accumulated count equals the `numberMatched` reported in the returned pages. A short page alone is not proof. Do not use `resultType=hits` as the completeness total: some servers cap it at the page size.

Common traps:

* WMS 1.3.0 with `EPSG:4326` may use latitude/longitude bbox order; `CRS:84` uses longitude/latitude.
* WFS often needs `count`/`startIndex` paging and an explicit `outputFormat` such as GeoJSON or GML.
* A WMS may not offer EPSG:3857 even when a web map requests it; read the CRS list in `GetCapabilities` and use the provider's WMTS/XYZ tiles for web maps when it does not.
* WMTS tile matrix sets may not be Web Mercator; read the matrix set before constructing tile URLs.

## Estonia-specific sources (regional context)

Start from the catalogs, then the dataset pages; take formats, layers, fields and packaging from there.

* **Ruumiandmete kataloog (Estonian spatial data catalog / INSPIRE metadata)** — the authoritative discovery point for Estonian geodata metadata, with a search UI and an API for machine retrieval:
  * Catalog: https://metadata.geoportaal.ee/geonetwork/srv/est/catalog.search#/home
  * API reference: https://metadata.geoportaal.ee/geonetwork/doc/api/index.html
  Use it to find the current, official records and OGC endpoints for any Estonian dataset (cadastre, roads, buildings, elevations) instead of guessing brochure URLs.
* **Maa- ja Ruumiamet (Estonian Land and Spatial Development Board, formerly Maa-amet) — Geoportal** — national datasets (topographic, cadastral, addresses, orthophotos, elevations, LiDAR) with per-dataset download pages and WMS / WFS / WMTS services:
  * Spatial data index: https://geoportaal.maaruum.ee/eng/spatial-data-p58.html
  * Many datasets offer bulk downloads by county (maakond) and municipality, a preferred path over WFS paging for whole-region pulls. Check each dataset page for the current packaging and formats.
* **Cadastral data (katastriüksused)** — authoritative cadastral units: https://geoportaal.maaruum.ee/eng/spatial-data/cadastral-data-p310.html
* **ETAK (Estonian Topographic Database)** — national vector base data (buildings, roads, water, land cover, relief and more), offered as downloads and through a WFS: https://geoportaal.maaruum.ee/est/ruumiandmed/eesti-topograafia-andmekogu/laadi-etak-andmed-alla-p609.html. Take the current service address and layer names from the catalog record or the service's `GetCapabilities`.
* **Licenses** — check the license linked by the particular dataset; do not label all agency products CC-BY. The ETAK download page links the agency's own open-data license, https://geoportaal.maaruum.ee/avaandmete-litsents. Do not substitute CC-BY for these terms. Record the license link, provider/dataset and data age or extraction date; include the terms or link when redistributing.
* **Pinning** — agency downloads are regenerated in place. Retain the actual bytes and SHA-256 (or a genuinely immutable provider version); a filename, URL or retrieval date alone is not an immutable pin.
* **Municipal portals** — some municipalities publish their own GIS data, sometimes more current and richer than OSM or Overture for the same themes. For example **Tartu** has https://geohub.tartulv.ee/ and **Tallinn** has https://www.tallinn.ee/et/geoportaal/ruumiandmed; there can be others.
* **Default CRS for Estonia: EPSG:3301 (L-EST97 / Estonian Coordinate System of 1997)**. Convert from WGS84 with `pyproj` or `gdalwarp -t_srs EPSG:3301`.

## MCP servers for catalog-driven discovery

For LLM-orchestrated workflows, these MCP servers replace manual catalog browsing:

| Server | Repo | What it does |
|---|---|---|
| **STAC MCP** | `BnJam/stac-mcp` | Search any STAC catalog (Microsoft PC by default), with `estimate_data_size` for lazy planning. Federated multi-catalog search. |
| **OSM MCP (Python)** | `jagan-shanmugam/open-streetmap-mcp` | Geocoding, POI search, routing primitives. Broad tool surface. |
| **OSM MCP (Go)** | `NERVsystems/osmmcp` | Performance-focused, OSRM + Nominatim under the hood. |
| **gis-mcp** | `mahdin75/gis-mcp` | Geometry ops + STAC-backed Sentinel/Landsat band downloads + map generation. |

A useful baseline configuration: STAC MCP + one OSM MCP + gis-mcp, plus a custom Overture or PostGIS MCP for organization-specific data.

### When discovery via MCP beats discovery via CLI

* Iterative refinement — "narrow this further", "what about this time window instead"
* Cross-catalog comparison
* Cost / size estimation before commit
* Mixing vector and raster discovery in one conversation

When the bbox and time window are already known and the task is purely batch ingestion, plain `pystac-client` is leaner.

## Reproducibility — pin everything

* Overture: pin release version, not `latest`; public buckets retain only recent releases, so mirror anything needed long term.
* STAC: pin item IDs in the manifest you save with the pipeline, not just (collection, bbox, time).
* OSM extracts: record the extract file timestamp.
* National data: record download date, the dataset page or catalog record, and the SHA-256 of the bytes.

A `data-manifest.json` next to outputs is enough; full DVC / lakeFS is overkill for most pipelines but useful for production.
