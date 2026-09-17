# Northstar Mobility — NYC Operations Hub Analysis (tenant alpha)

Private-database worked example for
[openmapstack-skills#43](https://github.com/jaakla/openmapstack-skills/issues/43):
identify promising NYC areas for a new operations/charging hub for tenant
`alpha` while respecting the fixture's enforced security model.

This is the **PostGIS + local-snapshots skeleton stage**. The BigQuery and
MotherDuck connectors, provisioning, and fixtures land in later steps of the
issue's implementation sequence; the design and the stage map live in
`docs/maintainers/nyc-private-mobility.md`.

## Architecture

```
live PostGIS (northstar_ops)                restricted reader: oms_alpha_reader
      ↓ openmapstack source snapshot        (RLS: tenant alpha, column grants)
data/source/*.parquet  (pinned, committed)
      ↓ pipeline.py                          never touches a live warehouse
data/derived/* + dashboard.html + validation/ + runs/
```

- Live warehouses are used for read-only discovery and explicitly approved
  snapshotting only. The accepted analysis runs from pinned local snapshots
  (`pin.class: local_snapshot`), so `openmapstack verify` works with **all
  warehouse credentials unset**.
- Provisioning identity (admin) is separate from the analysis identity. The
  OpenMapStack project references only `env:OMS_DEMO_POSTGIS_DSN`.
- Backend-enforced security is the fixture: row-level security, column
  grants, and an inaccessible `hr.driver_private` relation.

## Layout

| Path | Purpose |
|---|---|
| `project.yaml` | canonical manifest; scoring model and eligibility live here |
| `pipeline.py` | single canonical analysis from pinned snapshots (also `run_e2e.py`) |
| `provision.py` | infrastructure only: `postgis` / `all` / `verify` / `destroy` |
| `setup/postgis/{schema,seed,security}.sql` | fixture structure, deterministic seed (20260917), RLS/column-security boundary |
| `queries/*.sql` | the exact approved-snapshot queries (run through the restricted reader) |
| `data/source/` | pinned snapshots + manifest (immutable once captured) |
| `data/derived/` | zone metrics and ranked hub candidates |
| `validation/`, `runs/` | validation report and run records |
| `dashboard.html` | rendered view over project artifacts |

## Reproduce

```bash
pip install "openmapstack[geo,postgis]"

# 1. Provision the fixture (admin identity, one-time)
export OMS_DEMO_POSTGIS_ADMIN_DSN=...            # admin only, never in project.yaml
export OMS_DEMO_POSTGIS_READER_PASSWORD=...
python provision.py postgis

# 2. Capture approved snapshots through the restricted reader
export OMS_DEMO_POSTGIS_DSN=...                  # restricted reader DSN
openmapstack source snapshot . --source taxi_zones \
  --query "$(cat queries/postgis-taxi-zones.sql)" \
  --destination data/source/taxi_zones.parquet --approve --write-manifest
# (repeat for hubs, fleet_positions, customer_accounts)

# 3. Run the canonical analysis — credentials are no longer needed
python pipeline.py
openmapstack validate . --preflight
unset OMS_DEMO_POSTGIS_DSN OMS_DEMO_POSTGIS_ADMIN_DSN OMS_DEMO_POSTGIS_READER_PASSWORD
openmapstack verify .                            # must still pass
```

## Security model (backend-enforced)

- `oms_alpha_reader` sees only `tenant_id = 'alpha'` rows on every
  tenant-bearing table (row-level security policies in `security.sql`).
- `contact_name`, `contact_email`, `contract_value` on
  `ops.customer_accounts` are withheld by column grants: `SELECT *` and
  protected-column queries fail at the backend, so they can never reach a
  snapshot.
- `hr.driver_private` has no grants and no schema usage: entirely
  inaccessible.
- No credential appears in `project.yaml`, snapshots, logs, errors, or
  committed artifacts.

## Scope notes

- `A2`: historical trip demand is proxied by active customer accounts until
  the BigQuery leg lands; `A4`: market/amenity context scores 0 for all
  zones until the MotherDuck snapshot exists. The scoring weights
  (45/30/15/10) already match the canonical model and are recomputable from
  `data/derived/zone-metrics.parquet` alone.
- Zone geometries are the deterministic synthetic grid (A5); real NYC TLC
  taxi-zone polygons are a later, drop-in replacement.
