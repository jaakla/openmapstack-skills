#!/usr/bin/env python3
"""Canonical reproducible pipeline for examples/nyc-private-mobility.

Northstar Mobility — NYC operations/charging hub candidates (tenant alpha).

The pipeline runs exclusively from pinned local snapshots under
``data/source/`` (all captured through the restricted reader, so the
fixture's row-level security and column grants are baked into the inputs).
It never touches a live warehouse: provisioning and snapshotting belong to
``provision.py`` and ``openmapstack source snapshot``.

Flow:
    data/source/*.parquet  ->  zone metrics -> eligibility -> scoring
        -> data/derived/{zone-metrics.parquet, hub-candidates.parquet,
           hub-candidates.geojson}
        -> validation/latest-report.json + runs/run-*.json + dashboard.html

The scoring model lives in ``project.yaml`` (``scoring:``) and is recomputed
here from derived columns only; every assumption is recorded in
``interpretation.assumptions`` (A1-A5).
"""

from __future__ import annotations

import datetime
import json
import sys
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
)


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
        demand_by_zone AS (
            SELECT taxi_zone_id, count(*) AS n
            FROM read_parquet('{accounts}')
            WHERE is_active
            GROUP BY 1
        )
        SELECT z.zone_id, z.borough, z.zone_name, z.geom,
               coalesce(d.n, 0) AS demand_accounts,
               coalesce(f.n, 0) AS fleet_present,
               CAST(min(ST_Distance(z.centroid, h.g)) AS INTEGER) AS hub_distance_m
        FROM zones z
        CROSS JOIN hub_points h
        LEFT JOIN demand_by_zone d ON d.taxi_zone_id = z.zone_id
        LEFT JOIN fleet_by_zone f ON f.taxi_zone_id = z.zone_id
        GROUP BY 1, 2, 3, 4, 5, 6
        ORDER BY z.zone_id
        """
    ).fetchall()
    return [
        {
            "zone_id": row[0],
            "borough": row[1],
            "zone_name": row[2],
            "geom_wkb": row[3],
            "demand_accounts": row[4],
            "fleet_present": row[5],
            "hub_distance_m": row[6],
        }
        for row in rows
    ]


def score_candidates(metrics: list[dict], scoring: dict) -> list[dict]:
    """Apply the project.yaml scoring model; mutates and returns the metrics."""
    eligibility = scoring["eligibility"]
    weights = scoring["weights"]

    def eligible(zone: dict) -> bool:
        return (
            zone["demand_accounts"] >= eligibility["demand_accounts_min"]
            and zone["hub_distance_m"] >= eligibility["hub_distance_m_min"]
            and zone["fleet_present"] <= eligibility["fleet_present_max"]
        )

    pool = [zone for zone in metrics if eligible(zone)]
    if not pool:
        raise SystemExit("no eligible candidate zones; check the scoring.eligibility thresholds")
    max_demand = max(zone["demand_accounts"] for zone in pool)
    max_distance = max(zone["hub_distance_m"] for zone in pool)
    max_fleet = max(zone["fleet_present"] for zone in pool)
    for zone in metrics:
        zone.update(
            demand_score=None,
            coverage_gap_score=None,
            market_score=0.0,  # A4: no market context in this stage
            saturation_score=None,
            final_score=None,
        )
    for zone in pool:
        zone["demand_score"] = zone["demand_accounts"] / max_demand
        zone["coverage_gap_score"] = zone["hub_distance_m"] / max_distance
        zone["saturation_score"] = 1.0 - zone["fleet_present"] / max_fleet
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
        "fleet_present INTEGER, hub_distance_m INTEGER, demand_score DOUBLE, "
        "coverage_gap_score DOUBLE, market_score DOUBLE, saturation_score DOUBLE, "
        "final_score DOUBLE, geom GEOMETRY)"
    )
    duck.executemany(
        "INSERT INTO zone_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "ST_GeomFromWKB(?))",
        [
            (
                zone["zone_id"], zone["borough"], zone["zone_name"], zone["demand_accounts"],
                zone["fleet_present"], zone["hub_distance_m"], zone["demand_score"],
                zone["coverage_gap_score"], zone["market_score"], zone["saturation_score"],
                zone["final_score"], zone["geom_wkb"],
            )
            for zone in metrics
        ],
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
            "demand_accounts": zone["demand_accounts"],
            "fleet_present": zone["fleet_present"],
            "hub_distance_m": zone["hub_distance_m"],
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
        if zone["demand_accounts"] < thresholds["demand_accounts_min"]
        or zone["hub_distance_m"] < thresholds["hub_distance_m_min"]
        or zone["fleet_present"] > thresholds["fleet_present_max"]
    ]
    add("eligibility_thresholds", "passed" if not violating else "failed",
        "candidates satisfy every eligibility threshold", violations=violating)
    return checks


# -- run record + manifest ----------------------------------------------------


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
        "note": "all snapshots captured through the restricted reader oms_alpha_reader",
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
            for field in ("zone_id", "zone_name", "demand_accounts", "fleet_present", "hub_distance_m", "final_score")
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
<tr><th>Zone</th><th>Name</th><th>Demand (accounts)</th><th>Fleet present</th><th>Hub distance (m)</th><th>Score</th></tr>
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
<p>All private inputs are pinned local snapshots captured through the restricted
reader <code>oms_alpha_reader</code>; no live warehouse is queried at analysis time.</p>
</div>
</body>
</html>
"""
    (ROOT / "dashboard.html").write_text(html, encoding="utf-8")
    log("wrote dashboard.html")


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
        checks = run_checks(duck, snapshots, metrics, candidates, manifest["scoring"]["eligibility"])
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
