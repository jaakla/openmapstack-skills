-- Approved-snapshot query: customer account presence per zone.
-- The restricted reader has column-level grants only: contact_name,
-- contact_email and contract_value are withheld by the backend and can
-- never reach this snapshot. Row-level security limits rows to
-- tenant_id = 'alpha'.
-- Executed by the restricted reader through `openmapstack source snapshot`.

SELECT
    account_id,
    tenant_id,
    taxi_zone_id,
    account_name,
    is_active
FROM ops.customer_accounts
ORDER BY account_id
