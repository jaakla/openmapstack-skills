-- Northstar Mobility BigQuery fixture: security boundary
--
-- Enforced by BigQuery itself, not by the connector (issue #43):
--
--   * row access policies confine the restricted reader to tenant 'alpha' on
--     every tenant-bearing table;
--   * the analysis dataset is granted read-only -- and granted LAST, after
--     every policy exists, because a grant without a policy is a grant to
--     every tenant's rows. seed.sql revokes it before it drops the policies,
--     so the pair of files fails closed: the reader is either locked out or
--     filtered, never unfiltered;
--   * the restricted dataset is granted nothing at all, so it stays
--     inaccessible;
--   * column-level security on internal_cost and rider_reference needs a Data
--     Catalog taxonomy, which is a separate IAM object: it lives in
--     column-security.sql and is applied only when a policy tag is supplied.
--     `provision.py verify` reports it as not configured when it is absent --
--     never as if it had been applied.
--
-- Run as the provisioning/admin identity; the analysis identity is only ever
-- the grantee:
--
--   python provision.py bigquery --reader-principal serviceAccount:oms-alpha-reader@PROJECT.iam.gserviceaccount.com

-- -- nothing on the restricted dataset ----------------------------------------
-- Idempotent: revoking a grant that was never made is not an error, and this
-- is what keeps a re-run from leaving a stale grant behind.
REVOKE `roles/bigquery.dataViewer`
ON SCHEMA `:project`.`:restricted_dataset`
FROM :'reader_principal';

-- -- row-level security: only tenant 'alpha' is visible ----------------------
CREATE OR REPLACE ROW ACCESS POLICY alpha_only
ON `:project`.`:dataset`.trip_events
GRANT TO (:'reader_principal')
FILTER USING (tenant_id = 'alpha');

CREATE OR REPLACE ROW ACCESS POLICY alpha_only
ON `:project`.`:dataset`.zone_daily_demand
GRANT TO (:'reader_principal')
FILTER USING (tenant_id = 'alpha');

CREATE OR REPLACE ROW ACCESS POLICY alpha_only
ON `:project`.`:dataset`.vehicle_daily_metrics
GRANT TO (:'reader_principal')
FILTER USING (tenant_id = 'alpha');

-- -- read-only on the analysis dataset, and only now -------------------------
-- Last, deliberately: every policy above is already in force, so the reader
-- goes straight from no access to filtered access with no window in between.
GRANT `roles/bigquery.dataViewer`
ON SCHEMA `:project`.`:dataset`
TO :'reader_principal';
