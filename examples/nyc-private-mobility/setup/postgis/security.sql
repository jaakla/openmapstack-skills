-- Northstar Mobility PostGIS fixture: security boundary
--
-- Creates the restricted analysis identity and enforces the security model
-- the OpenMapStack connector must respect (issue #43):
--
--   * RLS: oms_alpha_reader sees only tenant_id = 'alpha' rows on every
--     tenant-bearing table;
--   * column grants: contact_name, contact_email and contract_value on
--     ops.customer_accounts are withheld, so SELECT * fails there;
--   * ops.taxi_zones is public-origin reference data: full SELECT;
--   * hr.driver_private is entirely inaccessible (no grants, no schema usage).
--
-- Provisioning/admin credentials must never be used for analysis. Run as the
-- admin identity; the reader password comes from a variable, never from this
-- file:
--
--   psql "$OMS_DEMO_POSTGIS_ADMIN_DSN" -v ON_ERROR_STOP=1 \
--        -v reader_name=oms_alpha_reader \
--        -v reader_password="$OMS_DEMO_POSTGIS_READER_PASSWORD" \
--        -f security.sql
--
-- provision.py performs the same :variable substitution when it applies this
-- file programmatically.

-- -- restricted analysis identity -------------------------------------------
CREATE ROLE :reader_name LOGIN PASSWORD :'reader_password';

GRANT USAGE ON SCHEMA ops TO :reader_name;
REVOKE CREATE ON SCHEMA ops FROM PUBLIC;

-- public-origin reference data: fully readable
GRANT SELECT ON ops.taxi_zones TO :reader_name;

-- tenant-bearing tables: RLS narrows rows, column grants narrow columns
GRANT SELECT (hub_id, tenant_id, taxi_zone_id, name, capacity, activated_on, geom)
    ON ops.hubs TO :reader_name;
GRANT SELECT (position_id, tenant_id, vehicle_id, taxi_zone_id, status, recorded_at, geom)
    ON ops.fleet_positions TO :reader_name;
GRANT SELECT (area_id, tenant_id, name, coverage_level, geom)
    ON ops.service_areas TO :reader_name;
-- contact_name, contact_email, contract_value are deliberately NOT granted:
-- SELECT * on this table must fail for the restricted reader.
GRANT SELECT (account_id, tenant_id, taxi_zone_id, account_name, is_active)
    ON ops.customer_accounts TO :reader_name;

-- hr.driver_private: entirely inaccessible
REVOKE ALL ON SCHEMA hr FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA hr FROM PUBLIC;

-- -- row-level security: only tenant 'alpha' is visible ----------------------
ALTER TABLE ops.hubs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.fleet_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.service_areas ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.customer_accounts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hubs_alpha_read ON ops.hubs;
CREATE POLICY hubs_alpha_read ON ops.hubs
    FOR SELECT TO :reader_name
    USING (tenant_id = 'alpha');

DROP POLICY IF EXISTS fleet_positions_alpha_read ON ops.fleet_positions;
CREATE POLICY fleet_positions_alpha_read ON ops.fleet_positions
    FOR SELECT TO :reader_name
    USING (tenant_id = 'alpha');

DROP POLICY IF EXISTS service_areas_alpha_read ON ops.service_areas;
CREATE POLICY service_areas_alpha_read ON ops.service_areas
    FOR SELECT TO :reader_name
    USING (tenant_id = 'alpha');

DROP POLICY IF EXISTS customer_accounts_alpha_read ON ops.customer_accounts;
CREATE POLICY customer_accounts_alpha_read ON ops.customer_accounts
    FOR SELECT TO :reader_name
    USING (tenant_id = 'alpha');
