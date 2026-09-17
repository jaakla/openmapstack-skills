# Northstar Mobility: private-database fixture design

Design and fixture contract for the private-database worked example
(`examples/nyc-private-mobility/`) and its deterministic eval fixture
(`evals/fixtures/mini-private-mobility/`). Motivated by
[openmapstack-skills#43](https://github.com/jaakla/openmapstack-skills/issues/43).

This document is navigation and rationale. Executable contracts live in the
files it points to.

## Scenario

One fictional company, **Northstar Mobility — NYC Operations Hub Analysis**.
Canonical question: identify promising NYC areas for a new operations/charging
hub for tenant `alpha` from historical trip demand, current fleet and hub
coverage, and market/POI context, while respecting all database access
restrictions. All synthetic business attributes are deterministic from the
checked-in seed `20260917`; no output may imply real NYC taxi records belong
to the fictional company.

Three backends play three enterprise roles:

| Backend | Role | Fixture database |
|---|---|---|
| BigQuery | historical analytical warehouse | `northstar_analytics` |
| PostGIS | operational GIS | `northstar_ops` |
| MotherDuck | private market-intelligence overlay | `northstar_market` |

## Core architecture rules

1. **Live warehouses are for read-only discovery and explicitly approved
   snapshotting only.** The accepted, reproducible analysis always runs from
   pinned local snapshots (`pin.class: local_snapshot`) under `data/source/`,
   exactly as `skills/open-map-stack/references/user-data-sources.md`
   requires. Backend time travel is never the long-term reproducibility
   mechanism.
2. **Provisioning identity ≠ analysis identity.** `provision.py` uses an
   admin credential; `project.yaml` always references the restricted reader
   (`env:OMS_DEMO_POSTGIS_DSN`, `env:GOOGLE_APPLICATION_CREDENTIALS`,
   `env:MOTHERDUCK_TOKEN`). Credentials never appear in `project.yaml`,
   snapshots, logs, errors, or committed artifacts — enforced by
   `openmapstack.sources.find_inline_credentials` and connector redaction.
3. **Backend-enforced security is the fixture, not a nice-to-have.** RLS row
   policies, column grants/policy tags, and inaccessible relations must be
   created by the provisioning scripts and exercised by the tests; the
   connector must behave correctly *under* them, not around them.
4. **Scoring logic lives in `project.yaml`** as an explicitly recomputable
   formula over derived columns, never hidden in Python only.

Acceptance gate: `unset` all warehouse credentials, then
`openmapstack verify examples/nyc-private-mobility` must still pass from the
committed snapshots.

## Cross-backend data model

Two conceptual keys join everything:

- `tenant_id` — drives RLS and permission tests (`alpha` is the RLS-visible
  analysis tenant; `beta`/`gamma` exist to prove isolation);
- `taxi_zone_id` — stable integer join key; geometry stays attached for real
  spatial operations.

All row generators are deterministic: a checked-in seed or stable hashes of
public source keys. Never platform `random()` without `setseed`, never
wall-clock data in fixture rows.

## PostGIS fixture (`northstar_ops`)

Owned by `examples/nyc-private-mobility/setup/postgis/{schema,seed,security}.sql`.

- Schemas/tables: `ops.taxi_zones` (public-origin reference geometry),
  `ops.hubs`, `ops.fleet_positions`, `ops.service_areas`,
  `ops.customer_accounts`, `hr.driver_private`.
- Restricted reader role `oms_alpha_reader`: RLS policies confine
  tenant-bearing tables to `tenant_id = 'alpha'`; column grants on
  `ops.customer_accounts` omit `contact_name`, `contact_email`,
  `contract_value`; `hr.driver_private` has no grants at all.
- Expected reader behaviour: permitted-column SELECT succeeds, `SELECT *`
  fails on the column-granted table, protected-column SELECT fails,
  other-tenant rows are invisible, `hr.driver_private` is inaccessible.
- Integration tests: `tests/test_private_fixture_postgis.py` (live tests run
  when `OPENMAPSTACK_TEST_PRIVATE_POSTGIS_ADMIN_DSN` points at an ephemeral
  PostGIS; the connector contract tests in `tests/test_connectors.py` remain
  the fake-driver layer).

## BigQuery fixture (`northstar_analytics`) — later stage

`trip_events`, `zone_daily_demand`, `vehicle_daily_metrics` derived from a
fixed subset of the BigQuery NYC Yellow Taxi public dataset plus deterministic
synthetic attributes; row access policy `tenant_id = 'alpha'`, column policy
tags on `internal_cost`/`rider_reference`, one inaccessible dataset path.
Connector `openmapstack/connectors/bigquery.py` adds `max_scan_bytes` (dry-run
byte estimate refused before execution) and normalises `GEOGRAPHY` to EPSG:4326
GeoParquet. Discovery row estimates must not be presented as RLS-visible row
counts.

## MotherDuck fixture (`northstar_market`) — later stage

`zone_market_scores`, `relevant_pois`, `analyst_annotations`: a real/shared
POI source (e.g. Foursquare Open Source Places) narrowed to a fixed NYC subset
plus private enrichment — the "large shared source + private enrichment =
private analytical dataset" enterprise pattern. Security for the canonical
fixture is private DB + dedicated token + read-only permissions; fine-grained
table security is an optional later profile. Connector
`openmapstack/connectors/motherduck.py` reuses the `md:` protocol; all
`ATTACH`/`INSTALL`/`COPY`/secret setup stays connector-controlled.

## Mini deterministic fixture (`evals/fixtures/mini-private-mobility/`)

Runs on ordinary CI with no credentials and no network. Regenerate with
`python gen.py` (idempotent, seed `20260917`); committed outputs are the
contract. File set:

| File | Content |
|---|---|
| `taxi-zones.geojson` | 8 zones, Polygon, EPSG:4326 |
| `trip-events.parquet` | 64 trips, two tenants, protected columns present |
| `fleet-positions.geojson` | 10 points, EPSG:2263 (deliberate mixed-CRS input), one NULL geometry |
| `hubs.geojson` | 2 existing hubs, tenant `alpha` |
| `pois.geojson` | 24 private-market POIs across categories |
| `market-scores.parquet` | per-zone market scores |
| `driver-private.parquet` | deliberately inaccessible relation (simulates `hr.driver_private`) |
| `access-matrix.yaml` | declares the simulated security model: visible tenant, protected columns, inaccessible relations |
| `expected.yaml` | exact hand-checkable values: visible row counts, accessible columns, candidate zone, aggregate demand, hub distances, POI counts, final score/ranking |

Deliberate hard cases baked in: two tenants (only `alpha` visible), protected
columns, one inaccessible relation, one mixed-CRS input, one NULL geometry,
one candidate zone with an unambiguous expected winner. `expected.yaml` values
are produced by the same generator that writes the data, so a later eval case
can recompute them independently and fail loudly on drift.

## Test layers (from issue #43)

- **A. Unit connector tests** — fake clients, no services (`tests/`).
- **B. Local PostGIS integration** — ephemeral PostGIS with the fixture SQL
  and RLS/column security; the mandatory live-DB leg (CI workflow
  `eval-warehouse.yml`).
- **C. Offline fixture evals** — committed mini snapshots, every PR, no
  credentials.
- **D. Optional live cloud integration** — BigQuery/MotherDuck only when
  secrets exist; PRs must not fail without them.

## Status (issue #43 implementation sequence)

Steps 1–5 covered by this change: design/fixture contract (this file),
`mini-private-mobility` generator + `expected.yaml`, PostGIS fixture SQL,
PostGIS RLS/column-security integration tests, and the
`examples/nyc-private-mobility` PostGIS + local-snapshot skeleton. BigQuery
and MotherDuck connectors, provisioning, and fixtures are later steps and are
intentionally absent.
