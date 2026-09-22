#!/usr/bin/env python3
"""Canonical reproducible pipeline for examples/nyc-private-mobility.

Northstar Mobility — NYC operations/charging hub candidates (tenant alpha).

The pipeline runs exclusively from pinned local snapshots under
``data/source/`` (each captured through its backend's restricted analysis
identity, so PostGIS row-level security, the BigQuery row access policy and
the column grants are all baked into the inputs).
It never touches a live warehouse: provisioning and snapshotting belong to
``provision.py`` and ``openmapstack source snapshot``.

Three backends contribute: BigQuery historical demand, PostGIS fleet and hub
coverage, MotherDuck market context -- combined locally, never joined live.

Flow:
    data/source/*.parquet  ->  zone metrics -> eligibility -> scoring
        -> data/derived/{zone-metrics.parquet, hub-candidates.parquet,
           hub-candidates.geojson}
        -> validation/latest-report.json + runs/run-*.json + dashboard.html
           + project.qgs/project.qgz

The scoring model lives in ``project.yaml`` (``scoring:``) and is recomputed
here from derived columns only; every assumption is recorded in
``interpretation.assumptions`` (A1-A5).
"""

from __future__ import annotations

import datetime
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import yaml

from openmapstack.checks.spatial import connect_spatial
from openmapstack.integrity import (
    canonical_file_set_hash,
    declared_input_paths,
    declared_output_paths,
    file_inventory,
    sha256_file,
)

ROOT = Path(__file__).resolve().parent
DERIVED = ROOT / "data" / "derived"
VALIDATION_DIR = ROOT / "validation"
RUNS_DIR = ROOT / "runs"

ANALYSIS_EPSG = 32618  # UTM 18N, metres — NYC metric CRS (assumption A3)
PROTECTED_COLUMNS = {"contact_name", "contact_email", "contract_value", "internal_cost", "rider_reference"}
REQUIRED_CHECKS = (
    "geometry_valid",
    "crs_known",
    "row_count_gt_zero",
    "no_null_zone_id",
    "rls_scope_alpha_only",
    "protected_columns_absent",
    "score_components_complete",
    "score_range",
    "eligibility_thresholds",
    "qgis_project_static_valid",
)

# Two CRSs, and the distinction matters: the candidates are stored in
# EPSG:4326 but an XYZ tile basemap is Web Mercator. Declaring the basemap as
# 4326 would leave QGIS assuming it needs no reprojection and paint the tiles
# in the wrong place -- the failure `qgis.every_layer_declares_crs` exists to
# catch, which it duly did on the first version of this generator.
CRS_DEFINITIONS = {
    4326: {
        "wkt": (
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
            'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
            'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
            'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]'
        ),
        "proj4": "+proj=longlat +datum=WGS84 +no_defs",
        "srsid": "3452",
        "description": "WGS 84",
        "projectionacronym": "longlat",
        "geographicflag": "true",
    },
    3857: {
        "wkt": (
            'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",'
            'SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
            'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
            'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
            'AUTHORITY["EPSG","4326"]],PROJECTION["Mercator_1SP"],'
            'PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],'
            'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
            'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],'
            'AXIS["Northing",NORTH],AUTHORITY["EPSG","3857"]]'
        ),
        "proj4": (
            "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 "
            "+units=m +nadgrids=@null +wktext +no_defs"
        ),
        "srsid": "3857",
        "description": "WGS 84 / Pseudo-Mercator",
        "projectionacronym": "merc",
        "geographicflag": "false",
    },
}
CANDIDATES_LAYER_ID = "hub_candidates_layer"
BASEMAP_LAYER_ID = "osm_basemap_layer"


def log(message: str) -> None:
    print(f"[pipeline] {message}", flush=True)


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


# -- inputs -------------------------------------------------------------------


def pinned_snapshot_paths(manifest: dict) -> dict[str, Path]:
    """Snapshot path per source key; only pinned local snapshots are inputs."""
    snapshots: dict[str, Path] = {}
    for key, block in (manifest.get("sources") or {}).items():
        pin = block.get("pin") if isinstance(block, dict) else None
        if not isinstance(pin, dict) or pin.get("class") != "local_snapshot":
            raise SystemExit(f"source {key!r} has no local_snapshot pin; run the approved snapshot first")
        relative = str(pin.get("path", ""))
        path = ROOT / relative
        if not relative.startswith("data/source/") or not path.is_file():
            raise SystemExit(
                f"source {key!r} pin path {relative!r} is missing; this pipeline never queries live warehouses"
            )
        snapshots[key] = path
    return snapshots


# -- metrics ------------------------------------------------------------------


def compute_zone_metrics(duck, snapshots: dict[str, Path]) -> list[dict]:
    """Per-zone operational metrics; all spatial maths in EPSG:32618 (A3)."""
    zones = sql_path(snapshots["taxi_zones"])
    hubs = sql_path(snapshots["hubs"])
    fleet = sql_path(snapshots["fleet_positions"])
    accounts = sql_path(snapshots["customer_accounts"])
    demand = sql_path(snapshots["zone_demand"])
    market = sql_path(snapshots["zone_market"])
    rows = duck.execute(
        f"""
        WITH zones AS (
            SELECT zone_id, borough, zone_name, geom,
                   ST_Centroid(ST_Transform(geom, 'OGC:CRS84', 'EPSG:{ANALYSIS_EPSG}')) AS centroid
            FROM read_parquet('{zones}')
        ),
        hub_points AS (
            SELECT ST_Transform(geom, 'OGC:CRS84', 'EPSG:{ANALYSIS_EPSG}') AS g
            FROM read_parquet('{hubs}')
        ),
        fleet_by_zone AS (
            SELECT taxi_zone_id, count(*) AS n
            FROM read_parquet('{fleet}')
            WHERE geom IS NOT NULL
            GROUP BY 1
        ),
        accounts_by_zone AS (
            SELECT taxi_zone_id, count(*) AS n
            FROM read_parquet('{accounts}')
            WHERE is_active
            GROUP BY 1
        ),
        demand AS (SELECT * FROM read_parquet('{demand}')),
        market AS (SELECT * FROM read_parquet('{market}'))
        SELECT z.zone_id, z.borough, z.zone_name, z.geom,
               coalesce(a.n, 0) AS demand_accounts,
               coalesce(f.n, 0) AS fleet_present,
               CAST(min(ST_Distance(z.centroid, h.g)) AS INTEGER) AS hub_distance_m,
               any_value(d.trips_total) AS trips_total,
               any_value(d.trips_peak_day) AS trips_peak_day,
               any_value(d.trips_stddev_day) AS trips_stddev_day,
               any_value(d.active_days) AS active_days,
               any_value(d.mean_trip_km) AS mean_trip_km,
               any_value(m.market_score_raw) AS market_score_raw,
               any_value(m.charging_pois) AS charging_pois,
               any_value(m.parking_pois) AS parking_pois,
               any_value(m.transit_pois) AS transit_pois,
               any_value(m.competitor_pois) AS competitor_pois,
               any_value(m.total_pois) AS total_pois
        FROM zones z
        CROSS JOIN hub_points h
        LEFT JOIN accounts_by_zone a ON a.taxi_zone_id = z.zone_id
        LEFT JOIN fleet_by_zone f ON f.taxi_zone_id = z.zone_id
        LEFT JOIN demand d ON d.taxi_zone_id = z.zone_id
        LEFT JOIN market m ON m.taxi_zone_id = z.zone_id
        GROUP BY 1, 2, 3, 4, 5, 6
        ORDER BY z.zone_id
        """
    ).fetchall()
    fields = (
        "zone_id", "borough", "zone_name", "geom_wkb", "demand_accounts", "fleet_present",
        "hub_distance_m", "trips_total", "trips_peak_day", "trips_stddev_day", "active_days",
        "mean_trip_km", "market_score_raw", "charging_pois", "parking_pois", "transit_pois",
        "competitor_pois", "total_pois",
    )
    return [dict(zip(fields, row)) for row in rows]


def score_candidates(metrics: list[dict], scoring: dict) -> list[dict]:
    """Apply the project.yaml scoring model; mutates and returns the metrics."""
    eligibility = scoring["eligibility"]
    weights = scoring["weights"]

    components = scoring["components"]
    amenity_full = components["amenity_pois_for_full_score"]
    competitor_full = components["competitor_pois_for_full_pressure"]

    def eligible(zone: dict) -> bool:
        return (
            (zone["trips_total"] or 0) >= eligibility["trips_total_min"]
            and zone["hub_distance_m"] >= eligibility["hub_distance_m_min"]
            and zone["fleet_present"] <= eligibility["fleet_present_max"]
        )

    def market_of(zone: dict) -> float:
        """Market context, recomputable from the columns in zone-metrics.parquet.

        Half the weight is Northstar's own per-zone score, the rest is what is
        physically there: amenities help, competitors do not.
        """
        amenities = zone["charging_pois"] + zone["parking_pois"] + zone["transit_pois"]
        amenity_score = min(1.0, amenities / amenity_full)
        competition = min(1.0, zone["competitor_pois"] / competitor_full)
        return round(
            0.5 * zone["market_score_raw"] + 0.3 * amenity_score + 0.2 * (1.0 - competition), 6
        )

    pool = [zone for zone in metrics if eligible(zone)]
    if not pool:
        raise SystemExit("no eligible candidate zones; check the scoring.eligibility thresholds")
    max_demand = max(zone["trips_total"] for zone in pool)
    max_distance = max(zone["hub_distance_m"] for zone in pool)
    max_fleet = max(zone["fleet_present"] for zone in pool)
    for zone in metrics:
        zone.update(
            demand_score=None,
            coverage_gap_score=None,
            market_score=None,
            saturation_score=None,
            final_score=None,
        )
    for zone in pool:
        zone["demand_score"] = zone["trips_total"] / max_demand
        zone["coverage_gap_score"] = zone["hub_distance_m"] / max_distance
        zone["saturation_score"] = 1.0 - zone["fleet_present"] / max_fleet
        zone["market_score"] = market_of(zone)
        zone["final_score"] = round(
            100
            * (
                weights["demand"] * zone["demand_score"]
                + weights["coverage_gap"] * zone["coverage_gap_score"]
                + weights["market"] * zone["market_score"]
                + weights["saturation"] * zone["saturation_score"]
            ),
            2,
        )
    return metrics


# -- outputs ------------------------------------------------------------------


def write_outputs(duck, metrics: list[dict], candidates: list[dict]) -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    duck.execute(
        "CREATE OR REPLACE TABLE zone_metrics ("
        "zone_id INTEGER, borough VARCHAR, zone_name VARCHAR, demand_accounts INTEGER, "
        "fleet_present INTEGER, hub_distance_m INTEGER, "
        "trips_total INTEGER, trips_peak_day INTEGER, trips_stddev_day DOUBLE, "
        "active_days INTEGER, mean_trip_km DOUBLE, market_score_raw DOUBLE, "
        "charging_pois INTEGER, parking_pois INTEGER, transit_pois INTEGER, "
        "competitor_pois INTEGER, total_pois INTEGER, demand_score DOUBLE, "
        "coverage_gap_score DOUBLE, market_score DOUBLE, saturation_score DOUBLE, "
        "final_score DOUBLE, geom GEOMETRY)"
    )
    # Every input the scoring model reads is stored beside the score, so a
    # reviewer can recompute final_score from this file and nothing else.
    columns = (
        "zone_id", "borough", "zone_name", "demand_accounts", "fleet_present", "hub_distance_m",
        "trips_total", "trips_peak_day", "trips_stddev_day", "active_days", "mean_trip_km",
        "market_score_raw", "charging_pois", "parking_pois", "transit_pois", "competitor_pois",
        "total_pois", "demand_score", "coverage_gap_score", "market_score", "saturation_score",
        "final_score",
    )
    duck.executemany(
        f"INSERT INTO zone_metrics VALUES ({', '.join('?' for _ in columns)}, ST_GeomFromWKB(?))",
        [tuple(zone[name] for name in columns) + (zone["geom_wkb"],) for zone in metrics],
    )
    metrics_parquet = (DERIVED / "zone-metrics.parquet").as_posix()
    candidates_parquet = (DERIVED / "hub-candidates.parquet").as_posix()
    # DuckDB's untyped GEOMETRY column drops the CRS on INSERT, so the storage
    # CRS is (re)applied in the COPY projection: the GeoParquet metadata must
    # read back as EPSG:4326.
    duck.execute(
        f"COPY (SELECT * REPLACE(ST_SetCRS(geom, 'EPSG:4326') AS geom) FROM zone_metrics) "
        f"TO '{metrics_parquet}' (FORMAT PARQUET)"
    )
    duck.execute(
        f"COPY (SELECT * REPLACE(ST_SetCRS(geom, 'EPSG:4326') AS geom) FROM zone_metrics "
        f"WHERE final_score IS NOT NULL ORDER BY final_score DESC, zone_id) "
        f"TO '{candidates_parquet}' (FORMAT PARQUET)"
    )
    features = []
    for zone in sorted(candidates, key=lambda item: (-item["final_score"], item["zone_id"])):
        geometry = duck.execute("SELECT ST_AsGeoJSON(ST_GeomFromWKB(?))", [zone["geom_wkb"]]).fetchone()[0]
        properties = {
            "zone_id": zone["zone_id"],
            "zone_name": zone["zone_name"],
            "trips_total": zone["trips_total"],
            "trips_peak_day": zone["trips_peak_day"],
            "trips_stddev_day": zone["trips_stddev_day"],
            "demand_accounts": zone["demand_accounts"],
            "fleet_present": zone["fleet_present"],
            "hub_distance_m": zone["hub_distance_m"],
            "charging_pois": zone["charging_pois"],
            "parking_pois": zone["parking_pois"],
            "competitor_pois": zone["competitor_pois"],
            "market_score_raw": zone["market_score_raw"],
            "demand_score": zone["demand_score"],
            "coverage_gap_score": zone["coverage_gap_score"],
            "market_score": zone["market_score"],
            "saturation_score": zone["saturation_score"],
            "final_score": zone["final_score"],
        }
        features.append(json.dumps({"type": "Feature", "geometry": json.loads(geometry), "properties": properties},
                                   separators=(",", ":")))
    payload = '{"type": "FeatureCollection", "features": [' + ",\n".join(features) + "]}\n"
    (DERIVED / "hub-candidates.geojson").write_text(payload, encoding="utf-8")
    log(f"wrote {len(metrics)} zone metrics and {len(candidates)} candidate zones")


# -- validation ---------------------------------------------------------------


def run_checks(duck, snapshots: dict[str, Path], metrics: list[dict], candidates: list[dict],
               thresholds: dict) -> list[dict]:
    """Domain checks. Every id declared in project.yaml validation must appear once."""
    checks: list[dict] = []

    def add(check_id: str, status: str, message: str, **details) -> None:
        checks.append({"id": check_id, "status": status, "message": message, **details})

    def q(sql: str):
        return duck.execute(sql).fetchall()

    invalid = q("SELECT count(*) FROM zone_metrics WHERE NOT ST_IsValid(geom)")[0][0]
    add("geometry_valid", "passed" if invalid == 0 else "failed",
        "all derived zone geometries valid", invalid_count=invalid, features_checked=len(metrics))

    actual_crs = sorted(
        {
            str(row[0])
            for path in ("zone-metrics.parquet", "hub-candidates.parquet")
            for row in q(f"SELECT DISTINCT ST_CRS(geom) FROM read_parquet('{(DERIVED / path).as_posix()}')")
        }
    )
    add("crs_known", "passed" if actual_crs == ["EPSG:4326"] else "failed",
        f"storage CRS of derived outputs is {actual_crs}", expected="EPSG:4326", actual=actual_crs)

    add("row_count_gt_zero", "passed" if metrics and candidates else "failed",
        "zone metrics and candidates non-empty", zone_rows=len(metrics), candidate_zones=len(candidates))

    nulls = sum(1 for zone in metrics if zone["zone_id"] is None)
    add("no_null_zone_id", "passed" if nulls == 0 else "failed", "zone ids complete", nulls=nulls)

    tenants: set[str] = set()
    for key in ("hubs", "fleet_positions", "customer_accounts"):
        found = q(f"SELECT DISTINCT tenant_id FROM read_parquet('{sql_path(snapshots[key])}')")
        tenants.update(str(row[0]) for row in found)
    add("rls_scope_alpha_only", "passed" if tenants == {"alpha"} else "failed",
        "tenant-bearing snapshots contain only the RLS-visible tenant",
        tenants=sorted(tenants), expected=["alpha"])

    protected: list[str] = []
    for key in ("hubs", "fleet_positions", "customer_accounts"):
        described = q(f"DESCRIBE SELECT * FROM read_parquet('{sql_path(snapshots[key])}')")
        names = {str(row[0]) for row in described}
        protected.extend(sorted(names & PROTECTED_COLUMNS))
    if (ROOT / "data/source/driver_private.parquet").exists():
        protected.append("driver_private.parquet must not be a snapshot (hr.driver_private is inaccessible)")
    add("protected_columns_absent", "passed" if not protected else "failed",
        "no protected column or inaccessible relation appears in data/source", findings=protected)

    incomplete = [
        zone["zone_id"]
        for zone in candidates
        if None in (zone["demand_score"], zone["coverage_gap_score"], zone["market_score"],
                    zone["saturation_score"], zone["final_score"])
    ]
    add("score_components_complete", "passed" if not incomplete else "failed",
        "every candidate has all score components", incomplete=incomplete)

    out_of_range = [zone["zone_id"] for zone in candidates if not 0 <= zone["final_score"] <= 100]
    add("score_range", "passed" if not out_of_range else "failed",
        "final scores within [0, 100]", out_of_range=out_of_range)

    violating = [
        zone["zone_id"]
        for zone in candidates
        if zone["trips_total"] < thresholds["trips_total_min"]
        or zone["hub_distance_m"] < thresholds["hub_distance_m_min"]
        or zone["fleet_present"] > thresholds["fleet_present_max"]
    ]
    add("eligibility_thresholds", "passed" if not violating else "failed",
        "candidates satisfy every eligibility threshold", violations=violating)
    return checks


# -- run record + manifest ----------------------------------------------------


def _environment() -> dict[str, str]:
    import platform

    import duckdb

    return {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "analysis_crs": f"EPSG:{ANALYSIS_EPSG}",
    }


def write_run_evidence(manifest: dict, checks: list[dict], snapshots: dict[str, Path],
                       started_at: str, completed_at: str) -> tuple[str, str]:
    """Write the validation report and run record; update runs.latest."""
    statuses = {check["status"] for check in checks}
    if "failed" in statuses:
        status = "failed"
    elif statuses - {"passed"}:
        status = "warning"
    else:
        status = "passed"
    run_id = "run-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")

    # data/source/manifest.json belongs to the immutable input set, so it is
    # written before the input inventory hash is taken.
    source_manifest = {
        "schema": "openmapstack-source-manifest/v1",
        "project": manifest["project"]["id"],
        "note": (
            "every snapshot was captured through that backend's restricted analysis identity: "
            "oms_alpha_reader on PostGIS, a read-only service account on BigQuery, "
            "a dedicated token on MotherDuck"
        ),
        "sources": {
            key: {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}
            for key, path in sorted(snapshots.items())
        },
    }
    (ROOT / "data/source/manifest.json").write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    input_paths = declared_input_paths(ROOT, manifest)
    output_paths = declared_output_paths(manifest)
    inputs_hash = canonical_file_set_hash(ROOT, input_paths)
    outputs_hash = canonical_file_set_hash(ROOT, output_paths)

    report = {
        "run_id": run_id,
        "schema": "openmapstack-project/v1",
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "inputs_hash": inputs_hash,
        "outputs_hash": outputs_hash,
        "checks": checks,
    }
    VALIDATION_DIR.mkdir(exist_ok=True)
    (VALIDATION_DIR / "latest-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    run_record = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "inputs_hash": inputs_hash,
        "outputs_hash": outputs_hash,
        # What actually produced these bytes. Without it a reader cannot tell
        # whether a hash mismatch is a real difference or a different DuckDB.
        "environment": _environment(),
        "source_manifest": "data/source/manifest.json",
        "validation_report": "validation/latest-report.json",
        "sources": [
            {"key": key, "sha256": sha256_file(path)}
            for key, path in sorted(snapshots.items())
        ],
        "inputs": file_inventory(ROOT, input_paths),
        "outputs": file_inventory(ROOT, output_paths),
    }
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(run_record, indent=2) + "\n", encoding="utf-8")

    updated = dict(manifest)
    updated.setdefault("runs", {})["latest"] = {
        "id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "inputs_hash": inputs_hash,
        "outputs_hash": outputs_hash,
        "record": {"path": f"runs/{run_id}.json"},
        "validation_report": {"path": "validation/latest-report.json"},
    }
    project_block = dict(updated.get("project") or {})
    project_block["updated_at"] = completed_at
    project_block["status"] = {"passed": "validated", "warning": "warning", "failed": "failed"}[status]
    updated["project"] = project_block
    (ROOT / "project.yaml").write_text(
        yaml.safe_dump(updated, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100),
        encoding="utf-8",
    )
    log(f"run {run_id} recorded with status {status}")
    return status, run_id


# -- dashboard ----------------------------------------------------------------


def write_dashboard(manifest: dict, checks: list[dict], candidates: list[dict], status: str) -> None:
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{zone[field]}</td>"
            for field in ("zone_id", "zone_name", "trips_total", "fleet_present", "hub_distance_m", "market_score", "final_score")
        )
        + "</tr>"
        for zone in candidates
    )
    check_rows = "".join(
        f'<tr><td>{check["id"]}</td><td class="{check["status"]}">{check["status"]}</td><td>{check["message"]}</td></tr>'
        for check in checks
    )
    provenance = "".join(f"<li>{item}</li>" for item in (manifest.get("presentation", {}).get("provenance_ui", {}) or {}).get("distinctions", []))
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{manifest['project']['title']}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 60rem; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
td, th {{ border: 1px solid #ccc; padding: .35rem .7rem; text-align: left; }}
.passed {{ color: #1a7f37; }} .warning {{ color: #9a6700; }} .failed {{ color: #cf222e; }}
.provenance {{ background: #f6f8fa; border: 1px solid #d0d7de; padding: .5rem 1rem; }}
</style>
</head>
<body>
<h1>{manifest['project']['title']}</h1>
<p><strong>Status:</strong> {status} · <strong>Tenant:</strong> alpha (RLS-visible)</p>
<h2>Hub candidates</h2>
<table>
<tr><th>Zone</th><th>Name</th><th>Trips (BigQuery)</th><th>Fleet present (PostGIS)</th><th>Hub distance m (PostGIS)</th><th>Market (MotherDuck)</th><th>Score</th></tr>
{rows}
</table>
<h2>Validation checks</h2>
<table>
<tr><th>Check</th><th>Status</th><th>Message</th></tr>
{check_rows}
</table>
<h2>Provenance</h2>
<div class="provenance">
<ul>
{provenance}
</ul>
<p>All private inputs are pinned local snapshots, each captured through that
backend's restricted analysis identity — <code>oms_alpha_reader</code> on
PostGIS, a read-only service account on BigQuery, a dedicated token on
MotherDuck. No live warehouse is queried at analysis time, and this page
rebuilds with every warehouse credential unset.</p>
</div>
</body>
</html>
"""
    (ROOT / "dashboard.html").write_text(html, encoding="utf-8")
    log("wrote dashboard.html")


# -- QGIS project -------------------------------------------------------------


def _spatialrefsys(epsg: int) -> ET.Element:
    """A complete CRS declaration: an authid alone is not enough for QGIS."""
    definition = CRS_DEFINITIONS[epsg]
    ref = ET.Element("spatialrefsys", nativeFormat="Wkt")
    ET.SubElement(ref, "wkt").text = definition["wkt"]
    ET.SubElement(ref, "proj4").text = definition["proj4"]
    ET.SubElement(ref, "srsid").text = definition["srsid"]
    ET.SubElement(ref, "srid").text = str(epsg)
    ET.SubElement(ref, "authid").text = f"EPSG:{epsg}"
    ET.SubElement(ref, "description").text = definition["description"]
    ET.SubElement(ref, "projectionacronym").text = definition["projectionacronym"]
    ET.SubElement(ref, "ellipsoidacronym").text = "EPSG:7030"
    ET.SubElement(ref, "geographicflag").text = definition["geographicflag"]
    return ref


def _srs(parent: ET.Element, epsg: int) -> None:
    ET.SubElement(parent, "srs").append(_spatialrefsys(epsg))


def _candidate_renderer(parent: ET.Element) -> None:
    """A graduated fill over final_score.

    A layer with no renderer draws with an invisible default, so the map would
    show less than the manifest claims -- `qgis.styles_declared` refuses it.
    The breaks are quartiles of the 0-100 score, so the legend reads the same
    way the dashboard table does.
    """
    renderer = ET.SubElement(
        parent, "renderer-v2", type="graduatedSymbol", attr="final_score",
        graduatedMethod="GraduatedColor", enableorderby="0",
    )
    ranges = ET.SubElement(renderer, "ranges")
    symbols = ET.SubElement(renderer, "symbols")
    bands = (
        ("0", "0", "50", "Lower half (0-50)", "255,245,235,140", "253,174,107,255"),
        ("1", "50", "65", "Moderate (50-65)", "253,208,162,170", "253,141,60,255"),
        ("2", "65", "75", "Strong (65-75)", "253,141,60,190", "230,85,13,255"),
        ("3", "75", "100", "Leading (75-100)", "217,71,1,210", "140,45,4,255"),
    )
    for name, lower, upper, label, fill, outline in bands:
        ET.SubElement(
            ranges, "range", lower=lower, upper=upper, symbol=name, label=label, render="true"
        )
        symbol = ET.SubElement(symbols, "symbol", type="fill", name=name, alpha="1")
        layer = ET.SubElement(symbol, "layer")
        layer.set("class", "SimpleFill")
        layer.set("enabled", "1")
        ET.SubElement(layer, "prop", k="color", v=fill)
        ET.SubElement(layer, "prop", k="outline_color", v=outline)
        ET.SubElement(layer, "prop", k="outline_width", v="0.46")


def write_qgis_project(manifest: dict) -> None:
    """Generate project.qgs and the project.qgz archive beside it.

    Generated rather than hand-authored so the datasources cannot drift from
    the outputs that actually exist -- the failure the Tartu example's static
    check was added to catch. Only GeoJSON is referenced: the derived Parquet
    needs a GDAL Parquet driver that a given QGIS install may not have, and a
    layer that fails to load is worse than one that is absent.
    """
    groups = manifest["presentation"]["map"]["layer_groups"]
    root = ET.Element("qgis", projectname="northstar-nyc-hub-siting", version="3.44.3")
    ET.SubElement(root, "homePath", path="")
    ET.SubElement(root, "title").text = manifest["project"]["title"]
    ET.SubElement(root, "autotransaction", active="0")
    ET.SubElement(root, "evaluateDefaultValues", active="0")
    ET.SubElement(root, "trust", active="0")
    ET.SubElement(root, "projectCrs").append(_spatialrefsys(4326))

    tree = ET.SubElement(root, "layer-tree-group")
    ET.SubElement(tree, "customproperties")
    layer_ids = {
        "result": (CANDIDATES_LAYER_ID, "Hub Candidates (ranked, tenant alpha)", "ogr"),
        "context": (BASEMAP_LAYER_ID, "OpenStreetMap (XYZ)", "wms"),
    }
    for group in groups:
        node = ET.SubElement(
            tree, "layer-tree-group", name=group["title"], expanded="1", checked="Qt.Checked"
        )
        layer_id, layer_name, provider = layer_ids[group["id"]]
        ET.SubElement(
            node, "layer-tree-layer", id=layer_id, name=layer_name,
            providerKey=provider, expanded="1", checked="Qt.Checked",
        )

    layers = ET.SubElement(root, "projectlayers")
    vector = ET.SubElement(
        layers, "maplayer", type="vector", geometry="Polygon",
        hasScaleBasedVisibilityFlag="0", readOnly="0", maxScale="0", minScale="1e+08",
        styleCategories="AllStyleCategories",
    )
    ET.SubElement(vector, "id").text = CANDIDATES_LAYER_ID
    ET.SubElement(vector, "datasource").text = "./data/derived/hub-candidates.geojson"
    ET.SubElement(vector, "layername").text = layer_ids["result"][1]
    _srs(vector, 4326)
    ET.SubElement(vector, "provider").text = "ogr"
    _candidate_renderer(vector)

    raster = ET.SubElement(
        layers, "maplayer", type="raster", hasScaleBasedVisibilityFlag="0",
        maxScale="0", minScale="1e+08", styleCategories="AllStyleCategories",
    )
    ET.SubElement(raster, "id").text = BASEMAP_LAYER_ID
    ET.SubElement(raster, "datasource").text = (
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
    )
    ET.SubElement(raster, "layername").text = layer_ids["context"][1]
    # Web Mercator: the tiles are, and saying 4326 here would misplace them.
    _srs(raster, 3857)
    ET.SubElement(raster, "provider").text = "wms"
    ET.SubElement(ET.SubElement(raster, "pipe"), "rasterrenderer", type="singlebandcolordata",
                  band="1", opacity="1", alphaBand="-1")

    properties = ET.SubElement(root, "properties")
    spatial = ET.SubElement(properties, "SpatialRefSys")
    enabled = ET.SubElement(spatial, "ProjectionsEnabled")
    enabled.set("type", "int")
    enabled.text = "1"
    ET.indent(root, space="  ")
    xml = (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )
    (ROOT / "project.qgs").write_text(xml, encoding="utf-8")
    # A fixed timestamp keeps the archive byte-identical across reruns, which
    # the clean-rerun output comparison depends on.
    info = zipfile.ZipInfo("project.qgs", date_time=(2026, 9, 22, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(ROOT / "project.qgz", "w") as archive:
        archive.writestr(info, xml)
    log("wrote project.qgs and project.qgz")


def validate_qgis_project(manifest: dict) -> dict:
    """Structural checks only.

    Loading the project through PyQGIS is the real proof and is not available
    here, so this asserts what can be asserted without QGIS: the archive is
    intact, the layer tree and the project layers describe the same layers,
    every local datasource exists, and every group the manifest declares is
    in the tree.
    """
    errors: list[str] = []
    try:
        with zipfile.ZipFile(ROOT / "project.qgz") as archive:
            corrupt = archive.testzip()
            if corrupt:
                errors.append(f"corrupt archive member: {corrupt}")
            xml = ET.fromstring(archive.read("project.qgs"))
        project_layers = xml.findall("./projectlayers/maplayer")
        project_ids = {layer.findtext("id") for layer in project_layers}
        tree_ids = {node.attrib.get("id") for node in xml.findall(".//layer-tree-layer")}
        if project_ids != tree_ids:
            errors.append(f"layer-tree IDs {sorted(tree_ids)} do not match project layers {sorted(project_ids)}")
        for layer in project_layers:
            source = (layer.findtext("datasource") or "").split("|", 1)[0]
            if source.startswith("./") and not (ROOT / source[2:]).exists():
                errors.append(f"missing datasource: {source}")
        tree_groups = {node.attrib.get("name") for node in xml.findall(".//layer-tree-group")}
        absent = [
            group["id"] for group in manifest["presentation"]["map"]["layer_groups"]
            if group["title"] not in tree_groups
        ]
        if absent:
            errors.append(f"manifest layer groups absent from the QGIS layer tree: {absent}")
        if xml.findtext("./projectCrs/spatialrefsys/authid") != "EPSG:4326":
            errors.append("project CRS is not the declared storage CRS EPSG:4326")
    except Exception as exc:  # noqa: BLE001 - report, never abort the run
        errors.append(f"{type(exc).__name__}: {exc}")
    return {
        "id": "qgis_project_static_valid",
        "status": "passed" if not errors else "failed",
        "message": "project.qgz is structurally valid and matches the declared layer groups",
        "project": "project.qgz",
        "errors": errors,
        "note": "structural only; loading through PyQGIS is not available in this environment",
    }


# -- entrypoint ---------------------------------------------------------------


def main() -> int:
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest = yaml.safe_load((ROOT / "project.yaml").read_text(encoding="utf-8"))
    snapshots = pinned_snapshot_paths(manifest)
    duck = connect_spatial()
    if duck is None:
        raise SystemExit("DuckDB Spatial is required: pip install 'openmapstack[geo]'")
    try:
        metrics = compute_zone_metrics(duck, snapshots)
        log(f"loaded {len(metrics)} zones from pinned snapshots")
        score_candidates(metrics, manifest["scoring"])
        candidates = [zone for zone in metrics if zone["final_score"] is not None]
        candidates.sort(key=lambda item: (-item["final_score"], item["zone_id"]))
        write_outputs(duck, metrics, candidates)
        write_qgis_project(manifest)
        checks = run_checks(duck, snapshots, metrics, candidates, manifest["scoring"]["eligibility"])
        checks.append(validate_qgis_project(manifest))
    finally:
        duck.close()
    completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    status, run_id = write_run_evidence(manifest, checks, snapshots, started_at, completed_at)
    write_dashboard(manifest, checks, candidates, status)
    for check in checks:
        marker = "ok " if check["status"] == "passed" else "!! "
        log(f"{marker}{check['id']}: {check['status']}")
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
