-- Northstar Mobility PostGIS fixture: deterministic seed
--
-- Every row is derived from md5('northstar|20260917|' || label) so the
-- fixture is byte-reproducible on any server version: no random(), no
-- wall-clock values. Re-running is idempotent (tables are truncated first).
--
--   psql "$OMS_DEMO_POSTGIS_ADMIN_DSN" -v ON_ERROR_STOP=1 -f seed.sql
--   (run after schema.sql)
--
-- Volumes follow the issue-43 sizing for the worked example:
--   taxi_zones 60, hubs 4, fleet_positions 480, service_areas 16,
--   customer_accounts 3600, driver_private 960.
-- Tenants alpha/beta/gamma all exist; only alpha is RLS-visible to the
-- restricted reader created by security.sql.

TRUNCATE ops.hubs, ops.fleet_positions, ops.service_areas,
         ops.customer_accounts, hr.driver_private, ops.taxi_zones
RESTART IDENTITY CASCADE;

CREATE OR REPLACE FUNCTION ops.fixture_rand(label text, modulus integer)
RETURNS integer LANGUAGE sql IMMUTABLE AS $$
    SELECT ((('x' || substr(md5('northstar|20260917|' || label), 1, 8))::bit(32)::bigint % modulus) + modulus) % modulus
$$;

-- -- 60 synthetic grid zones over the NYC study bbox (EPSG:4326) -------------
INSERT INTO ops.taxi_zones (zone_id, borough, zone_name, zone_source, geom)
SELECT
    101 + g,
    'Manhattan',
    'Grid Zone ' || (101 + g),
    'synthetic-grid',
    ST_MakeEnvelope(
        -74.030 + (g % 12) * 0.010,
        40.700 + (g / 12) * 0.015,
        -74.030 + (g % 12) * 0.010 + 0.010,
        40.700 + (g / 12) * 0.015 + 0.015,
        4326)
FROM generate_series(0, 59) AS g;

-- -- 4 existing hubs for tenant alpha, at zone centroids --------------------
INSERT INTO ops.hubs (hub_id, tenant_id, taxi_zone_id, name, capacity, activated_on, geom)
SELECT
    'H' || g,
    'alpha',
    zone.zone_id,
    'Northstar Hub ' || g,
    20 + ops.fixture_rand('hub-cap-' || g, 31),
    date '2026-03-01' + ops.fixture_rand('hub-day-' || g, 180),
    ST_Centroid(zone.geom)
FROM generate_series(1, 4) AS g
JOIN LATERAL (
    SELECT zone_id, geom FROM ops.taxi_zones
    ORDER BY zone_id OFFSET (g - 1) * 14 LIMIT 1
) zone ON true;

-- -- 480 fleet positions, ~80% alpha ----------------------------------------
INSERT INTO ops.fleet_positions (tenant_id, vehicle_id, taxi_zone_id, status, recorded_at, geom)
SELECT
    CASE WHEN ops.fixture_rand('fleet-tenant-' || g, 10) < 8 THEN 'alpha' ELSE 'beta' END,
    'NV-' || (100 + ops.fixture_rand('fleet-veh-' || g, 900)),
    zone.zone_id,
    (ARRAY['idle', 'on_trip', 'charging', 'maintenance'])[1 + ops.fixture_rand('fleet-status-' || g, 4)],
    timestamptz '2026-09-01 06:00:00+00'
        + make_interval(hours => ops.fixture_rand('fleet-hour-' || g, 17),
                        mins => ops.fixture_rand('fleet-min-' || g, 60)),
    ST_SetSRID(ST_MakePoint(
        -74.030 + zone.col * 0.010 + (0.1 + 0.8 * ops.fixture_rand('fleet-fx-' || g, 10000) / 10000.0) * 0.010,
        40.700 + zone.row * 0.015 + (0.1 + 0.8 * ops.fixture_rand('fleet-fy-' || g, 10000) / 10000.0) * 0.015
    ), 4326)
FROM generate_series(1, 480) AS g
JOIN LATERAL (
    SELECT
        zone_id, geom,
        (zone_id - 101) % 12 AS col,
        (zone_id - 101) / 12 AS row
    FROM ops.taxi_zones
    ORDER BY zone_id
    OFFSET ops.fixture_rand('fleet-zone-' || g, 60) LIMIT 1
) zone ON true;

-- -- 16 service areas, ~2/3 alpha -------------------------------------------
INSERT INTO ops.service_areas (area_id, tenant_id, name, coverage_level, geom)
SELECT
    'SA' || lpad(g::text, 2, '0'),
    CASE WHEN ops.fixture_rand('sa-tenant-' || g, 3) < 2 THEN 'alpha' ELSE 'beta' END,
    'Northstar Service Area ' || g,
    CASE WHEN ops.fixture_rand('sa-level-' || g, 3) = 0 THEN 'extended' ELSE 'core' END,
    ST_Buffer(zone.geom::geography, 500 + ops.fixture_rand('sa-radius-' || g, 400))::geometry
FROM generate_series(1, 16) AS g
JOIN LATERAL (
    SELECT zone_id, geom FROM ops.taxi_zones
    ORDER BY zone_id
    OFFSET ops.fixture_rand('sa-zone-' || g, 60) LIMIT 1
) zone ON true;

-- -- 3600 customer accounts: alpha ~60%, beta ~30%, gamma ~10% ---------------
INSERT INTO ops.customer_accounts
    (tenant_id, taxi_zone_id, account_name, contact_name, contact_email, contract_value, is_active)
SELECT
    CASE
        WHEN ops.fixture_rand('ca-tenant-' || g, 10) < 6 THEN 'alpha'
        WHEN ops.fixture_rand('ca-tenant-' || g, 10) < 9 THEN 'beta'
        ELSE 'gamma'
    END,
    101 + ops.fixture_rand('ca-zone-' || g, 60),
    'Account ' || lpad(g::text, 5, '0'),
    'Contact ' || lpad(g::text, 5, '0'),
    'contact' || lpad(g::text, 5, '0') || '@accounts.example.invalid',
    500 + ops.fixture_rand('ca-value-' || g, 95000) + (ops.fixture_rand('ca-cents-' || g, 100) / 100.0),
    ops.fixture_rand('ca-active-' || g, 10) < 9
FROM generate_series(1, 3600) AS g;

-- -- 960 private HR driver rows (never visible to the restricted reader) -----
INSERT INTO hr.driver_private (driver_id, tenant_id, full_name, phone, license_number, home_zone_id)
SELECT
    'D-' || lpad(g::text, 4, '0'),
    CASE
        WHEN ops.fixture_rand('drv-tenant-' || g, 10) < 7 THEN 'alpha'
        WHEN ops.fixture_rand('drv-tenant-' || g, 10) < 9 THEN 'beta'
        ELSE 'gamma'
    END,
    'Private Driver ' || lpad(g::text, 4, '0'),
    '+1-212-' || lpad((200 + ops.fixture_rand('drv-ph-' || g, 799))::text, 3, '0') || '-'
        || lpad(ops.fixture_rand('drv-ph2-' || g, 10000)::text, 4, '0'),
    'DL-' || upper(substr(md5('northstar|20260917|drv-lic-' || g), 1, 10)),
    101 + ops.fixture_rand('drv-zone-' || g, 60)
FROM generate_series(1, 960) AS g;

DROP FUNCTION ops.fixture_rand(text, integer);

ANALYZE ops.taxi_zones;
ANALYZE ops.hubs;
ANALYZE ops.fleet_positions;
ANALYZE ops.service_areas;
ANALYZE ops.customer_accounts;
