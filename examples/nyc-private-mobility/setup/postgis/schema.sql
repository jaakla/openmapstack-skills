-- Northstar Mobility PostGIS fixture: schema (examples/nyc-private-mobility)
-- Issue: https://github.com/jaakla/openmapstack-skills/issues/43
--
-- Structural layer only; deterministic rows live in seed.sql and the
-- security boundary in security.sql. Run as the provisioning/admin identity:
--
--   psql "$OMS_DEMO_POSTGIS_ADMIN_DSN" -v ON_ERROR_STOP=1 -f schema.sql
--
-- Tables follow the cross-backend data model from
-- docs/maintainers/nyc-private-mobility.md: every tenant-bearing table
-- carries tenant_id, and taxi_zone_id is the stable join key to the zone
-- reference geometry.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS hr;

REVOKE ALL ON SCHEMA hr FROM PUBLIC;

-- Public-origin reference geometry (NYC TLC taxi zones). The seed loads a
-- deterministic synthetic grid stand-in; replacing it with real TLC zone
-- polygons must not change any other table.
CREATE TABLE IF NOT EXISTS ops.taxi_zones (
    zone_id     integer PRIMARY KEY,
    borough     text NOT NULL,
    zone_name   text NOT NULL,
    zone_source text NOT NULL DEFAULT 'synthetic-grid',
    geom        geometry(Polygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS taxi_zones_geom_gix ON ops.taxi_zones USING GIST (geom);

-- Existing charging/operations hubs (tenant-bearing).
CREATE TABLE IF NOT EXISTS ops.hubs (
    hub_id       text PRIMARY KEY,
    tenant_id    text NOT NULL,
    taxi_zone_id integer NOT NULL REFERENCES ops.taxi_zones (zone_id),
    name         text NOT NULL,
    capacity     integer NOT NULL CHECK (capacity > 0),
    activated_on date NOT NULL,
    geom         geometry(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS hubs_geom_gix ON ops.hubs USING GIST (geom);

-- Current fleet positions (tenant-bearing); the analysis counts active
-- vehicles per zone, so the row-level policy directly shapes coverage.
CREATE TABLE IF NOT EXISTS ops.fleet_positions (
    position_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    text NOT NULL,
    vehicle_id   text NOT NULL,
    taxi_zone_id integer NOT NULL REFERENCES ops.taxi_zones (zone_id),
    status       text NOT NULL CHECK (status IN ('idle', 'on_trip', 'charging', 'maintenance')),
    recorded_at  timestamptz NOT NULL,
    geom         geometry(Point, 4326)
);

CREATE INDEX IF NOT EXISTS fleet_positions_geom_gix ON ops.fleet_positions USING GIST (geom);

-- Service-area polygons (tenant-bearing).
CREATE TABLE IF NOT EXISTS ops.service_areas (
    area_id        text PRIMARY KEY,
    tenant_id      text NOT NULL,
    name           text NOT NULL,
    coverage_level text NOT NULL CHECK (coverage_level IN ('core', 'extended')),
    geom           geometry(Polygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS service_areas_geom_gix ON ops.service_areas USING GIST (geom);

-- Customer accounts (tenant-bearing, column-protected). The restricted
-- reader must never see contact_name, contact_email, or contract_value.
CREATE TABLE IF NOT EXISTS ops.customer_accounts (
    account_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      text NOT NULL,
    taxi_zone_id   integer NOT NULL REFERENCES ops.taxi_zones (zone_id),
    account_name   text NOT NULL,
    contact_name   text NOT NULL,
    contact_email  text NOT NULL,
    contract_value numeric(12, 2) NOT NULL,
    is_active      boolean NOT NULL DEFAULT true
);

-- Fully private HR data: the restricted reader gets no grants at all.
CREATE TABLE IF NOT EXISTS hr.driver_private (
    driver_id     text PRIMARY KEY,
    tenant_id     text NOT NULL,
    full_name     text NOT NULL,
    phone         text NOT NULL,
    license_number text NOT NULL,
    home_zone_id  integer REFERENCES ops.taxi_zones (zone_id)
);
