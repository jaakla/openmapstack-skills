# Northstar Mobility — NYC Operations Hub Analysis (tenant alpha)

Private-database worked example for
[openmapstack-skills#43](https://github.com/jaakla/openmapstack-skills/issues/43):
identify promising NYC areas for a new operations/charging hub for tenant
`alpha` while respecting the fixture's enforced security model.

All three backends are now implemented: **PostGIS** (operational GIS),
**BigQuery** (historical warehouse), and **MotherDuck** (private market
overlay). Each has a connector, fixture SQL, provisioning, and a security
boundary.

What is **not** yet here: the committed `data/source/` snapshots are still
the PostGIS ones, so the canonical pipeline's demand and market inputs remain
the placeholders described under *Scope notes*. Capturing the BigQuery and
MotherDuck snapshots needs a billed GCP project and a MotherDuck account;
until then their legs are provisioned and testable but not pinned. The design
and the stage map live in `docs/maintainers/nyc-private-mobility.md`.

## Architecture

```
live PostGIS    (northstar_ops)        reader: oms_alpha_reader   RLS + column grants
live BigQuery   (northstar_analytics)  reader: service account    row access policies
live MotherDuck (northstar_market)     reader: read-scoped token  private database
      ↓ openmapstack source snapshot --approve   (read-only, dry-run first)
data/source/*.parquet  (pinned, committed)
      ↓ pipeline.py                             never touches a live warehouse
data/derived/* + dashboard.html + validation/ + runs/
```

- Live warehouses are used for read-only discovery and explicitly approved
  snapshotting only. The accepted analysis runs from pinned local snapshots
  (`pin.class: local_snapshot`), so `openmapstack verify` works with **all
  warehouse credentials unset**.
- Provisioning identity (admin) is separate from the analysis identity. The
  OpenMapStack project references only the restricted readers
  (`env:OMS_DEMO_POSTGIS_DSN`, `env:GOOGLE_APPLICATION_CREDENTIALS`,
  `env:MOTHERDUCK_TOKEN`).
- Backend-enforced security is the fixture, not decoration: row-level
  security and row access policies, column grants, and relations the reader
  cannot reach at all (`hr.driver_private`, `driver_costs`).

## Layout

| Path | Purpose |
|---|---|
| `project.yaml` | canonical manifest; scoring model and eligibility live here |
| `pipeline.py` | single canonical analysis from pinned snapshots (also `run_e2e.py`) |
| `provision.py` | infrastructure only: `postgis` / `bigquery` / `motherduck` / `all` / `verify` / `destroy` |
| `fixture.yaml` | the access matrix: what each backend enforces, and what is only a convention |
| `setup/postgis/{schema,seed,security}.sql` | fixture structure, deterministic seed (20260917), RLS/column-security boundary |
| `setup/bigquery/{schema,seed,security}.sql` | two datasets, row access policies, and the never-granted restricted dataset |
| `setup/bigquery/column-security.sql` | optional policy-tag step, applied only with `--policy-tag` |
| `setup/motherduck/{schema,seed,security}.sql` | private market overlay and its analysis views (plain DuckDB SQL, so tests execute it) |
| `queries/*.sql` | the exact approved-snapshot queries (run through the restricted reader) |
| `data/source/` | pinned snapshots + manifest (immutable once captured) |
| `data/derived/` | zone metrics and ranked hub candidates |
| `validation/`, `runs/` | validation report and run records |
| `dashboard.html` | rendered view over project artifacts |

## Reproduce

```bash
pip install "openmapstack[geo,postgis,bigquery,motherduck]"

# 1. Provision the fixtures (admin identities, one-time). `all` provisions
#    every backend whose credentials are set and reports the rest as skipped.
export OMS_DEMO_POSTGIS_ADMIN_DSN=...            # admin only, never in project.yaml
export OMS_DEMO_POSTGIS_READER_PASSWORD=...
export OMS_DEMO_BIGQUERY_PROJECT=...
export OMS_DEMO_BIGQUERY_ADMIN_CREDENTIALS=...   # admin key file
export OMS_DEMO_BIGQUERY_READER_PRINCIPAL=serviceAccount:oms-alpha-reader@PROJECT.iam.gserviceaccount.com
export OMS_DEMO_MOTHERDUCK_ADMIN_TOKEN=...
python provision.py all

# 2. Check the boundary through the restricted readers, not the admins.
export OMS_DEMO_POSTGIS_DSN=...                  # restricted reader DSN
export GOOGLE_APPLICATION_CREDENTIALS=...        # restricted reader key file
export MOTHERDUCK_TOKEN=...                      # read-scoped token
python provision.py verify

# 3. Capture approved snapshots through the restricted readers
openmapstack source snapshot . --source taxi_zones \
  --query "$(cat queries/postgis-taxi-zones.sql)" \
  --destination data/source/taxi_zones.parquet --approve --write-manifest
# (repeat for hubs, fleet_positions, customer_accounts; BigQuery snapshots
#  also take --max-scan-bytes, and are dry-run at the backend first)

# 4. Run the canonical analysis — credentials are no longer needed
python pipeline.py
openmapstack validate . --preflight
unset OMS_DEMO_POSTGIS_DSN OMS_DEMO_POSTGIS_ADMIN_DSN OMS_DEMO_POSTGIS_READER_PASSWORD \
      GOOGLE_APPLICATION_CREDENTIALS MOTHERDUCK_TOKEN OMS_DEMO_MOTHERDUCK_ADMIN_TOKEN \
      OMS_DEMO_BIGQUERY_ADMIN_CREDENTIALS
openmapstack verify .                            # must still pass
```

`provision.py destroy` removes every backend it has admin credentials for.

## Security model

`fixture.yaml` is the full access matrix, including which restrictions the
backend enforces and which are only conventions. In summary:

### PostGIS (backend-enforced)

- `oms_alpha_reader` sees only `tenant_id = 'alpha'` rows on every
  tenant-bearing table (row-level security policies in `security.sql`).
- `contact_name`, `contact_email`, `contract_value` on
  `ops.customer_accounts` are withheld by column grants: `SELECT *` and
  protected-column queries fail at the backend, so they can never reach a
  snapshot.
- `hr.driver_private` has no grants and no schema usage: entirely
  inaccessible.

### BigQuery (backend-enforced, with one optional part)

- Row access policies confine the reader to tenant `alpha` on `trip_events`,
  `zone_daily_demand` and `vehicle_daily_metrics`. `taxi_zones` is
  public-origin reference geometry: no tenant column, no policy, fully
  readable — the same split the PostGIS fixture uses.
- `northstar_analytics_restricted.driver_costs` is granted to nobody.
- Column-level security on `internal_cost` and `rider_reference` needs a Data
  Catalog policy tag. Without `--policy-tag` it is **not applied**, and
  `provision.py verify` prints `NOT CONFIGURED` rather than a pass.
- Every query is dry-run before execution and refused above
  `--max-scan-bytes`; the executed job also carries `maximum_bytes_billed`.
  On a table with a row access policy BigQuery returns *no* byte estimate, so
  the pre-execution check cannot run there and the plan says so
  (`scan_estimated: false`) rather than implying a cheap query. `taxi_zones`
  carries no policy and does report an estimate.
- `Table.num_rows` ignores row access policies, so discovery reports it as an
  estimate and never as the reader's visible row count.

### MotherDuck (token-scoped)

- Two independent read-only layers, and only one is guaranteed:
  - the connector attaches the database `READ_ONLY`, which DuckDB enforces —
    verified against live MotherDuck, where an `INSERT` through that session
    is refused outright;
  - a dedicated **read-scoped token** bounds what the credential can do
    anywhere else. Read-scoped tokens need a higher MotherDuck plan tier, and
    without one `provision.py verify` reports the identity layer as
    `NOT CONFIGURED` — not as a pass.
- The admin token is never the analysis token.
- `market.analyst_annotations` informs the scores and is never republished.
  That is a convention this analysis honours, not an enforced grant, and
  `fixture.yaml` records it as such.
- A MotherDuck session needs network access, so file confinement via
  `enable_external_access` is not available here.

### Everywhere

- No credential appears in `project.yaml`, snapshots, logs, errors, or
  committed artifacts.

## Scope notes

- `A2`: historical trip demand is proxied by active customer accounts, and
  `A4`: market/amenity context scores 0 for all zones. Both placeholders stay
  until the BigQuery and MotherDuck snapshots are captured and pinned — the
  connectors and fixtures exist, the pinned bytes do not. The scoring weights
  (45/30/15/10) already match the canonical model and are recomputable from
  `data/derived/zone-metrics.parquet` alone.
- Zone geometries are the deterministic synthetic grid (A5); real NYC TLC
  taxi-zone polygons are a later, drop-in replacement.
