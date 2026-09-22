-- Northstar Mobility BigQuery fixture: column-level security (optional)
--
-- BigQuery column-level security is a Data Catalog object, not a SQL grant:
-- the policy tag must already exist in a taxonomy, and the analysis identity
-- must NOT hold `roles/datacatalog.categoryFineGrainedReader` on it. Creating
-- a taxonomy needs the Data Catalog API and its own IAM, which is why this is
-- a separate, explicitly requested step:
--
--   python provision.py bigquery --policy-tag projects/P/locations/L/taxonomies/T/policyTags/N
--
-- Without it the two columns below remain readable by anyone who can read the
-- table, and `provision.py verify` says so. A fixture that quietly skipped
-- this step while reporting a clean security check would be worse than one
-- that does not apply it at all.

ALTER TABLE `:project`.`:dataset`.trip_events
ALTER COLUMN internal_cost
SET OPTIONS (policy_tags = STRUCT([:'policy_tag'] AS names));

ALTER TABLE `:project`.`:dataset`.trip_events
ALTER COLUMN rider_reference
SET OPTIONS (policy_tags = STRUCT([:'policy_tag'] AS names));
