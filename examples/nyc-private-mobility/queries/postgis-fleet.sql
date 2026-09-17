-- Approved-snapshot query: current fleet positions.
-- Row-level security confines this to tenant_id = 'alpha' for the restricted
-- reader; only located vehicles contribute to zone coverage.
-- Executed by the restricted reader through `openmapstack source snapshot`.

SELECT
    position_id,
    tenant_id,
    vehicle_id,
    taxi_zone_id,
    status,
    recorded_at,
    geom
FROM ops.fleet_positions
ORDER BY position_id
