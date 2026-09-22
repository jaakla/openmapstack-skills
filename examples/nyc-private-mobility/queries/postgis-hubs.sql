-- Approved-snapshot query: existing Northstar hubs.
-- Row-level security confines this to tenant_id = 'alpha' for the restricted
-- reader; the snapshot therefore contains only alpha hubs.
-- Executed by the restricted reader through `openmapstack source snapshot`.

SELECT
    hub_id,
    tenant_id,
    taxi_zone_id,
    name,
    capacity,
    activated_on,
    geom
FROM ops.hubs
ORDER BY hub_id
