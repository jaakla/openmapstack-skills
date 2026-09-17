#!/usr/bin/env python3
"""Deterministic generator for the mini-private-mobility eval fixture.

Regenerates every committed artifact in this directory from the checked-in
seed ``20260917``. Run from this directory:

    python gen.py

Everything is derived from md5 hashes of stable strings (never platform
``random``, never wall-clock), so the outputs are byte-identical for the
GeoJSON/YAML files on any machine. Parquet files are written with DuckDB and
compared logically by the determinism test.

The fixture simulates the private-database security model as data:

- two tenants; only ``alpha`` is the RLS-visible analysis tenant;
- ``trip-events.parquet`` carries protected columns (``internal_cost``,
  ``rider_reference``) that an access matrix denies;
- ``driver-private.parquet`` is the deliberately inaccessible relation
  (the local stand-in for ``hr.driver_private``);
- ``fleet-positions.geojson`` is EPSG:2263 (mixed-CRS input) and contains
  one feature with a NULL geometry;
- ``market-scores.parquet`` is missing zone 106 on purpose, so the
  "market data present" eligibility rule is exercisable.

``expected.yaml`` holds the exact hand-checkable answers; its values are
computed by this generator from the same functions that emit the data, so a
later eval case can recompute them independently and fail loudly on drift.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent


def _connect_spatial() -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with Spatial loaded, via the repo's helper if available."""
    try:
        from openmapstack.checks.spatial import connect_spatial

        connection = connect_spatial()
        if connection is not None:
            return connection
    except ImportError:
        pass
    connection = duckdb.connect()
    connection.execute("LOAD spatial")
    return connection

SEED = "20260917"

# -- deterministic primitives -------------------------------------------------


def h(*parts: str, mod: int) -> int:
    """A deterministic pseudo-random integer in [0, mod)."""
    digest = hashlib.md5("|".join((SEED, *parts)).encode()).hexdigest()
    return int(digest[:12], 16) % mod


def hex_id(*parts: str, length: int = 8) -> str:
    return hashlib.md5("|".join((SEED, *parts)).encode()).hexdigest()[:length]


def rnd(value: float, digits: int) -> float:
    return round(value, digits)


# -- shared geometry ----------------------------------------------------------

# A 4x2 synthetic grid over lower Manhattan; zone ids follow the classic
# 1xx Manhattan convention so the join key reads naturally.
LON0, LAT0, CELL_LON, CELL_LAT = -74.02, 40.70, 0.02, 0.07
GRID = {  # zone_id -> (col, row); row 1 is the northern band
    101: (0, 1), 102: (1, 1), 103: (2, 1), 104: (3, 1),
    105: (0, 0), 106: (1, 0), 107: (2, 0), 108: (3, 0),
}
ZONES = dict(sorted(GRID.items()))


def zone_polygon(zone_id: int) -> list[list[float]]:
    col, row = GRID[zone_id]
    lon, lat = LON0 + col * CELL_LON, LAT0 + row * CELL_LAT
    return [
        [rnd(lon, 6), rnd(lat, 6)],
        [rnd(lon + CELL_LON, 6), rnd(lat, 6)],
        [rnd(lon + CELL_LON, 6), rnd(lat + CELL_LAT, 6)],
        [rnd(lon, 6), rnd(lat + CELL_LAT, 6)],
        [rnd(lon, 6), rnd(lat, 6)],
    ]


def zone_centroid(zone_id: int) -> tuple[float, float]:
    col, row = GRID[zone_id]
    return (LON0 + (col + 0.5) * CELL_LON, LAT0 + (row + 0.5) * CELL_LAT)


def point_in_zone(zone_id: int, tag: str) -> tuple[float, float]:
    col, row = GRID[zone_id]
    fx, fy = h("pt-fx", tag, mod=10_000) / 10_000, h("pt-fy", tag, mod=10_000) / 10_000
    lon = LON0 + (col + 0.1 + 0.8 * fx) * CELL_LON
    lat = LAT0 + (row + 0.1 + 0.8 * fy) * CELL_LAT
    return rnd(lon, 6), rnd(lat, 6)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km on the mean-Earth sphere (R=6371.0088)."""
    radius = 6371.0088
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(x))


# -- fixture parameters (the deliberate design) -------------------------------

TENANTS = ("alpha", "beta")  # alpha is the RLS-visible analysis tenant
ALPHA_PICKUPS = {101: 3, 102: 2, 103: 4, 104: 5, 105: 2, 106: 3, 107: 6, 108: 12}
BETA_PICKUPS = {101: 4, 102: 3, 103: 3, 104: 4, 105: 4, 106: 3, 107: 3, 108: 3}
PROTECTED_COLUMNS = ("internal_cost", "rider_reference")
INACCESSIBLE = "driver-private.parquet"
MARKET_ABSENT_ZONES = (106,)

FLEET_BY_ZONE = {101: 2, 102: 1, 103: 2, 104: 1, 105: 2, 106: 1, 107: 1, 108: 0}
NULL_GEOMETRY_ZONE = 103  # one fleet position has a NULL geometry

HUBS = {  # both belong to tenant alpha
    "H1": {"zone": 101, "capacity": 40},
    "H2": {"zone": 105, "capacity": 25},
}

# zone -> (charging_score, parking_score, transport_hub_score, competitor_count, priority)
MARKET = {
    101: (70, 60, 80, 3, "medium"),
    102: (55, 50, 60, 2, "low"),
    103: (65, 70, 55, 4, "medium"),
    104: (80, 75, 65, 2, "high"),
    105: (50, 55, 70, 5, "low"),
    107: (85, 80, 60, 1, "high"),
    108: (95, 90, 85, 0, "high"),
}
POI_CATEGORIES = ("charging_station", "parking", "transit_hub", "competitor", "cafe")
POI_COUNTS = {101: 4, 102: 2, 103: 3, 104: 4, 105: 3, 106: 3, 107: 2, 108: 3}

ELIGIBILITY = {
    "rule": "market score row present AND alpha pickup demand >= 4",
    "min_demand": 4,
}
WEIGHTS = {"demand": 0.45, "coverage_gap": 0.30, "market": 0.15, "saturation": 0.10}


# -- writers ------------------------------------------------------------------


def write_geojson(name: str, features: list[dict]) -> None:
    payload = {"type": "FeatureCollection", "features": features}
    (HERE / name).write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def write_parquet(name: str, columns: list[tuple[str, str]], rows: list[tuple]) -> None:
    duck = _connect_spatial()
    try:
        definition = ", ".join(f'"{cname}" {ctype}' for cname, ctype in columns)
        duck.execute(f"CREATE TABLE staging ({definition})")
        placeholders = ", ".join("?" for _ in columns)
        if rows:
            duck.executemany(f"INSERT INTO staging VALUES ({placeholders})", rows)
        target = (HERE / name).as_posix().replace("'", "''")
        duck.execute(f"COPY staging TO '{target}' (FORMAT PARQUET)")
    finally:
        duck.close()


# -- per-file generators ------------------------------------------------------


def gen_taxi_zones() -> None:
    features = [
        feature(
            {"type": "Polygon", "coordinates": [zone_polygon(zone_id)]},
            {"taxi_zone_id": zone_id, "borough": "Manhattan", "zone_name": f"Northstar Grid {zone_id}"},
        )
        for zone_id in ZONES
    ]
    write_geojson("taxi-zones.geojson", features)


def gen_trip_events() -> list[tuple]:
    rows: list[tuple] = []
    trip_number = 0
    for tenant, counts in (("alpha", ALPHA_PICKUPS), ("beta", BETA_PICKUPS)):
        for zone_id in sorted(counts):
            for index in range(counts[zone_id]):
                trip_number += 1
                tag = f"trip-{tenant}-{zone_id}-{index}"
                pickup = point_in_zone(zone_id, tag + "-pu")
                dropoff_zone = sorted(ZONES)[h("dz", tag, mod=len(ZONES))]
                dropoff = point_in_zone(dropoff_zone, tag + "-do")
                pickup_ts = datetime(2026, 6, 1) + timedelta(
                    days=h("day", tag, mod=92),
                    hours=6 + h("hour", tag, mod=18),
                    minutes=h("minute", tag, mod=60),
                )
                distance_km = rnd(1.0 + h("dist", tag, mod=90) / 10.0, 1)
                gross = rnd(distance_km * 3.5 + h("rev", tag, mod=500) / 100.0, 2)
                internal = rnd(distance_km * 1.2 + 2.0, 2)
                rows.append(
                    (
                        f"T-{trip_number:05d}",
                        tenant,
                        f"NV-{h('veh', tag, mod=900) + 100:03d}",
                        f"D-{h('drv', tag, mod=900) + 100:03d}",
                        pickup_ts.isoformat(sep=" "),
                        pickup_ts.isoformat(sep=" ") if zone_id != dropoff_zone else pickup_ts.isoformat(sep=" "),
                        zone_id,
                        dropoff_zone,
                        pickup[0],
                        pickup[1],
                        dropoff[0],
                        dropoff[1],
                        distance_km,
                        gross,
                        internal,
                        f"RR-{hex_id('rider', tag)}",
                        "premium" if h("class", tag, mod=4) == 0 else "standard",
                    )
                )
    write_parquet(
        "trip-events.parquet",
        [
            ("trip_id", "VARCHAR"), ("tenant_id", "VARCHAR"), ("vehicle_id", "VARCHAR"), ("driver_id", "VARCHAR"),
            ("pickup_ts", "TIMESTAMP"), ("dropoff_ts", "TIMESTAMP"), ("pickup_zone_id", "INTEGER"),
            ("dropoff_zone_id", "INTEGER"), ("pickup_lon", "DOUBLE"), ("pickup_lat", "DOUBLE"),
            ("dropoff_lon", "DOUBLE"), ("dropoff_lat", "DOUBLE"), ("distance_km", "DOUBLE"),
            ("gross_revenue", "DOUBLE"), ("internal_cost", "DOUBLE"), ("rider_reference", "VARCHAR"),
            ("service_class", "VARCHAR"),
        ],
        rows,
    )
    return rows


def gen_fleet_positions() -> None:
    # EPSG:2263 (NYC Long Island, ftUS) on purpose: a mixed-CRS input that any
    # consumer must reproject before metric analysis.
    duck = _connect_spatial()
    try:
        features: list[dict] = []
        index = 0
        for zone_id in sorted(FLEET_BY_ZONE):
            for slot in range(FLEET_BY_ZONE[zone_id]):
                index += 1
                tag = f"fleet-{zone_id}-{slot}"
                vehicle = f"NV-{h('fveh', tag, mod=900) + 100:03d}"
                is_null = zone_id == NULL_GEOMETRY_ZONE and slot == 1
                properties = {
                    "vehicle_id": vehicle,
                    "tenant_id": "alpha",
                    "taxi_zone_id": zone_id,
                    "status": "maintenance_unknown" if is_null else ("on_trip" if h("st", tag, mod=2) else "idle"),
                    "recorded_at": f"2026-09-01T{6 + h('fh', tag, mod=17):02d}:{h('fm', tag, mod=60):02d}:00Z",
                }
                if is_null:
                    features.append(feature(None, properties))
                    continue
                lon, lat = point_in_zone(zone_id, tag)
                (x, y) = duck.execute(
                    "SELECT ST_X(g), ST_Y(g) FROM (SELECT ST_Transform(ST_Point(CAST(? AS DOUBLE), CAST(? AS DOUBLE)), 'EPSG:4326', 'EPSG:2263') AS g)",
                    [lon, lat],
                ).fetchone()
                features.append(
                    feature(
                        {"type": "Point", "coordinates": [rnd(x, 3), rnd(y, 3)]},
                        properties,
                    )
                )
    finally:
        duck.close()
    payload = {
        "type": "FeatureCollection",
        # The old (pre-RFC-7946) crs member: GDAL-based readers honour it.
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2263"}},
        "features": features,
    }
    (HERE / "fleet-positions.geojson").write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def gen_hubs() -> None:
    features = []
    for hub_id in sorted(HUBS):
        spec = HUBS[hub_id]
        lon, lat = zone_centroid(spec["zone"])
        features.append(
            feature(
                {"type": "Point", "coordinates": [rnd(lon, 6), rnd(lat, 6)]},
                {
                    "hub_id": hub_id,
                    "tenant_id": "alpha",
                    "taxi_zone_id": spec["zone"],
                    "name": f"Northstar Hub {hub_id}",
                    "capacity": spec["capacity"],
                    "activated_on": "2026-03-01",
                },
            )
        )
    write_geojson("hubs.geojson", features)


def gen_pois() -> None:
    features = []
    index = 0
    for zone_id in sorted(POI_COUNTS):
        for slot in range(POI_COUNTS[zone_id]):
            index += 1
            tag = f"poi-{zone_id}-{slot}"
            category = POI_CATEGORIES[h("cat", tag, mod=len(POI_CATEGORIES))]
            lon, lat = point_in_zone(zone_id, tag)
            features.append(
                feature(
                    {"type": "Point", "coordinates": [lon, lat]},
                    {
                        "poi_id": f"P-{index:03d}",
                        "taxi_zone_id": zone_id,
                        "category": category,
                        "name": f"Northstar POI {index:03d} ({category})",
                    },
                )
            )
    write_geojson("pois.geojson", features)


def gen_market_scores() -> list[tuple]:
    rows = []
    for zone_id in sorted(MARKET):
        charging, parking, transport, competitor, priority = MARKET[zone_id]
        tag = f"market-{zone_id}"
        note = {
            "high": "Priority corridor per Q3 strategy review.",
            "medium": "Steady context; revisit after hub siting.",
            "low": "No near-term action.",
        }[priority]
        rows.append(
            (
                zone_id,
                POI_COUNTS[zone_id],
                charging,
                parking,
                transport,
                competitor,
                priority,
                f"AN-{hex_id('note', tag, length=6)}: {note}",
            )
        )
    write_parquet(
        "market-scores.parquet",
        [
            ("taxi_zone_id", "INTEGER"), ("poi_count", "INTEGER"), ("parking_score", "INTEGER"),
            ("charging_score", "INTEGER"), ("transport_hub_score", "INTEGER"), ("competitor_count", "INTEGER"),
            ("strategic_priority", "VARCHAR"), ("analyst_note", "VARCHAR"),
        ],
        rows,
    )
    return rows


def gen_driver_private() -> list[tuple]:
    rows = []
    for index in range(1, 7):
        tag = f"driver-private-{index}"
        rows.append(
            (
                f"D-{index:03d}",
                TENANTS[index % 2],
                f"Private Driver {index:03d}",
                f"+1-212-{h('ph1', tag, mod=900) + 100:03d}-{h('ph2', tag, mod=10000):04d}",
                f"DL-{hex_id('license', tag, length=10).upper()}",
            )
        )
    write_parquet(
        "driver-private.parquet",
        [
            ("driver_id", "VARCHAR"), ("tenant_id", "VARCHAR"), ("full_name", "VARCHAR"),
            ("phone", "VARCHAR"), ("license_number", "VARCHAR"),
        ],
        rows,
    )
    return rows


def gen_access_matrix(trip_rows: list[tuple], market_rows: list[tuple]) -> None:
    alpha_visible = sum(1 for row in trip_rows if row[1] == "alpha")
    beta_hidden = sum(1 for row in trip_rows if row[1] == "beta")
    null_fleet = sum(
        1
        for zone_id, slot_count in FLEET_BY_ZONE.items()
        for slot in range(slot_count)
        if zone_id == NULL_GEOMETRY_ZONE and slot == 1
    )
    payload = {
        "schema": "openmapstack-mini-access-matrix/v1",
        "seed": SEED,
        "tenants": {"rls_visible": "alpha", "hidden": "beta"},
        "relations": {
            "taxi-zones.geojson": {"accessible": True, "rows": len(ZONES)},
            "trip-events.parquet": {
                "accessible": True,
                "rows": {"total": len(trip_rows), "alpha_visible": alpha_visible, "beta_hidden": beta_hidden},
                "protected_columns": list(PROTECTED_COLUMNS),
                "note": "protected columns simulate BigQuery policy tags / denied column grants",
            },
            "fleet-positions.geojson": {
                "accessible": True,
                "rows": {"total": sum(FLEET_BY_ZONE.values()), "null_geometry": null_fleet},
                "crs": "EPSG:2263",
                "note": "mixed-CRS input relative to the EPSG:4326 zones",
            },
            "hubs.geojson": {"accessible": True, "rows": len(HUBS), "tenants": ["alpha"]},
            "pois.geojson": {"accessible": True, "rows": sum(POI_COUNTS.values())},
            "market-scores.parquet": {
                "accessible": True,
                "rows": len(market_rows),
                "absent_zones": list(MARKET_ABSENT_ZONES),
                "note": "zone 106 has no market row: exercises the 'market data present' eligibility rule",
            },
            INACCESSIBLE: {
                "accessible": False,
                "reason": "simulates hr.driver_private: no grants for the restricted reader",
            },
        },
    }
    import yaml

    (HERE / "access-matrix.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True), encoding="utf-8"
    )


# -- expected values ----------------------------------------------------------


def compute_expected(trip_rows: list[tuple]) -> dict:
    alpha_demand = {zone: ALPHA_PICKUPS[zone] for zone in sorted(ALPHA_PICKUPS)}
    hubs_xy = {hub_id: zone_centroid(spec["zone"]) for hub_id, spec in HUBS.items()}
    hub_distance = {
        zone: rnd(min(haversine_km(zone_centroid(zone), xy) for xy in hubs_xy.values()), 3)
        for zone in sorted(ZONES)
    }
    located_fleet = {
        zone: FLEET_BY_ZONE[zone] - (1 if zone == NULL_GEOMETRY_ZONE else 0) for zone in sorted(ZONES)
    }
    eligible = sorted(
        zone
        for zone in sorted(ZONES)
        if zone not in MARKET_ABSENT_ZONES and alpha_demand[zone] >= ELIGIBILITY["min_demand"]
    )
    max_demand = max(alpha_demand[zone] for zone in eligible)
    max_distance = max(hub_distance[zone] for zone in eligible)
    max_competitor = max(MARKET[zone][3] for zone in eligible)
    ranking = []
    for zone in eligible:
        charging, parking, _transport, competitor, _priority = MARKET[zone]
        demand_score = alpha_demand[zone] / max_demand
        gap_score = hub_distance[zone] / max_distance
        market_score = (charging + parking) / 200.0
        saturation_score = 1.0 - competitor / max_competitor
        score = rnd(
            100
            * (
                WEIGHTS["demand"] * demand_score
                + WEIGHTS["coverage_gap"] * gap_score
                + WEIGHTS["market"] * market_score
                + WEIGHTS["saturation"] * saturation_score
            ),
            2,
        )
        ranking.append({"zone": zone, "score": score})
    ranking.sort(key=lambda item: (-item["score"], item["zone"]))
    return {
        "schema": "openmapstack-mini-expected/v1",
        "fixture": "mini-private-mobility",
        "seed": SEED,
        "counts": {
            "taxi_zones": len(ZONES),
            "trip_events": {
                "total": len(trip_rows),
                "alpha_visible": sum(1 for row in trip_rows if row[1] == "alpha"),
                "beta_hidden": sum(1 for row in trip_rows if row[1] == "beta"),
            },
            "fleet_positions": {
                "total": sum(FLEET_BY_ZONE.values()),
                "located": sum(located_fleet.values()),
                "null_geometry": 1,
            },
            "hubs": len(HUBS),
            "pois": sum(POI_COUNTS.values()),
            "market_scores": len(MARKET),
            "driver_private_rows_hidden": 6,
        },
        "security": {
            "rls_visible_tenant": "alpha",
            "hidden_tenant": "beta",
            "protected_columns": list(PROTECTED_COLUMNS),
            "inaccessible_relations": [INACCESSIBLE],
            "market_absent_zones": list(MARKET_ABSENT_ZONES),
            "mixed_crs_inputs": {"fleet-positions.geojson": "EPSG:2263"},
        },
        "alpha_pickups_by_zone": alpha_demand,
        "located_fleet_by_zone": located_fleet,
        "hub_distance_km_by_zone": {str(zone): hub_distance[zone] for zone in sorted(hub_distance)},
        "poi_counts_by_zone": {str(zone): POI_COUNTS[zone] for zone in sorted(POI_COUNTS)},
        "eligibility": {**ELIGIBILITY, "eligible_zones": eligible},
        "scoring": {
            "weights": WEIGHTS,
            "demand_score": "alpha pickups / max eligible alpha pickups",
            "coverage_gap_score": "hub_distance_km / max eligible hub_distance_km",
            "market_score": "(charging_score + parking_score) / 200",
            "saturation_score": "1 - competitor_count / max eligible competitor_count",
            "final_score": "100 * (0.45*demand + 0.30*coverage_gap + 0.15*market + 0.10*saturation), 2 decimals",
        },
        "ranking": ranking,
        "candidate_zone": ranking[0]["zone"],
    }


def main() -> None:
    gen_taxi_zones()
    trip_rows = gen_trip_events()
    gen_fleet_positions()
    gen_hubs()
    gen_pois()
    market_rows = gen_market_scores()
    gen_driver_private()
    gen_access_matrix(trip_rows, market_rows)
    expected = compute_expected(trip_rows)
    import yaml

    (HERE / "expected.yaml").write_text(
        yaml.safe_dump(expected, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(f"regenerated {len(list(HERE.glob('*')))} artifacts in {HERE}")


if __name__ == "__main__":
    main()
