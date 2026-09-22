# User data sources — warehouses, credentials, snapshots, clean reruns

Read this when an analysis must read the user's own tables: a PostGIS
database, a BigQuery dataset, a MotherDuck database, a DuckDB file, or a
local protected directory of GeoParquet/GeoPackage files that
is not a public download. It covers what `references/data-sources.md` does
not: data that has an owner, a credential, and no published version.

Treat warehouse access as a **connector and security problem**, not only a
documentation problem. The rules below are enforced by `openmapstack validate`
and `openmapstack verify`; the CLI implements them for the four verified
backends, and the rest of this file says what to do by hand elsewhere.

## The four rules

1. **Credentials by reference.** `project.yaml` never contains a password,
   a token, a key, or a DSN with a password in it. `access.connection` is a
   reference: `env:NAME`, `service:NAME` (an entry in `pg_service.conf`),
   `keyring:NAME`, or `file:/absolute/path/outside/the/project`. Both
   `validate` (`source.credentials`) and `verify`
   (`provenance.no_inline_credentials`) scan every source for embedded
   secrets and fail the project when they find one. Their findings name the
   manifest path and the pattern, never the secret.
2. **Discovery is read-only.** A connector session opens with
   `default_transaction_read_only = on` and a statement timeout, lists
   tables, geometry columns, SRIDs, and row estimates, and only ever runs
   a single `SELECT`. DML, DDL, `COPY`, `ATTACH`, `INSTALL` and `SET` are
   rejected before anything reaches the server, and so is any query that
   names a source of its own: `read_csv()`, `read_parquet()`,
   `read_json_auto()`, `ST_Read()`, `postgres_query()`, `sqlite_scan()` and
   friends, along with a bare `FROM 'some/path.parquet'` or
   `FROM 'https://…'`, which DuckDB would resolve as a file or URL. Read the
   relations the connector exposed.
3. **Materialising data locally needs explicit approval.**
   `openmapstack source snapshot` is a dry run by default: it reports the
   schema and row count the query would copy. Only `--approve` writes the
   snapshot, and it writes under `data/source/` only, never over an
   existing file, and never beyond the row and byte limits. On a backend
   that bills by bytes scanned, the query is dry-run at the backend first
   and refused before execution if the estimate exceeds `--max-scan-bytes`.
4. **A warehouse table is pinned only by a pin class.** A timestamp string
   is not a pin. Either the bytes are frozen locally (`local_snapshot`,
   hash-matched) or the backend can serve that exact state again
   (`backend_snapshot` with an identifier and a retention limit). An
   expired or inaccessible backend snapshot is reported as
   `not_reproducible`. See `project-spec.md` section 2.2.

## Declaring a warehouse source

```yaml
sources:
  parcels:
    role: authoritative_input
    provider: City GIS department
    dataset: cadastral parcels (warehouse copy)
    source_url: postgresql://geo-prod.internal/gis      # identity only, no credentials
    access:
      method: postgis
      connection: {ref: "env:PARCELS_DSN"}
      retrieved_at: "2026-08-30T10:00:00Z"
    warehouse:
      backend: postgis            # duckdb | postgis | bigquery | motherduck are verified
      account: geo-prod
      database: gis
      schema: cadastre
      table: parcels
      query_sha256: "sha256:..."  # written by `source snapshot`
      schema_sha256: "sha256:..."
    pin:
      class: local_snapshot
      path: data/source/parcels.parquet
      sha256: "sha256:..."
      captured_at: "2026-08-30T10:00:00Z"
    version:
      identifier: "cadastre.parcels @ pg_current_snapshot 1001:1001: on 2026-08-30"
      published_at: 2026-08-30
    selection:
      filter: "municipality = 'Tartu linn'"
    license: {name: "Internal — see data owner", url: https://intranet.example/gis-data-policy}
    schema: {crs: EPSG:3301, key: cadastral_id, columns: [cadastral_id, land_use, geom]}
    rationale: The warehouse copy is the department's authoritative parcel layer.
```

## The CLI path (DuckDB, PostGIS, BigQuery, MotherDuck)

```bash
# 1. Read-only discovery: what is there, which column is geometry, which SRID.
openmapstack source discover project.yaml --source parcels
openmapstack source discover project.yaml --source parcels --json

# 2. Dry run: schema, row count, and digests of the query you intend to freeze.
openmapstack source snapshot project.yaml --source parcels \
  --query "SELECT cadastral_id, land_use, geom FROM cadastre.parcels WHERE municipality = 'Tartu linn'" \
  --destination data/source/parcels.parquet

# 3. Materialise, after the user has approved the row count and the bytes.
openmapstack source snapshot project.yaml --source parcels --query-file queries/parcels.sql \
  --destination data/source/parcels.parquet --approve --max-rows 200000 --timeout 120

# 4. Record the pin (printed as YAML; --write-manifest rewrites project.yaml
#    and drops YAML comments, so most projects paste the block instead).
```

The snapshot is GeoParquet with geometry typed and, where the installed
DuckDB Spatial supports it, carrying the source SRID. The command returns the
`pin` block, the `warehouse` digests, and `access.retrieved_at` to place in
the manifest. Once placed, `openmapstack validate` reports `source.pin` as
`passed` with `pin_class: local_snapshot`.

### DuckDB local files

With `warehouse.backend: duckdb` and no `access.connection`, the connector
root is the project's own `data/source/`. Every geodata file under it is
exposed as a view named by its relative path, so a query reads
`FROM "parcels.geojson"` and never spells a filesystem path. File access is
confined to that root (`allowed_directories` + `enable_external_access =
false`); a query that reaches outside it fails. A `.duckdb` database is
attached read-only when the connection names one.

### PostGIS

`access.connection` resolves to a DSN through the reference. The session is
read-only with `statement_timeout`; discovery reads `geometry_columns` and
planner estimates; the snapshot fetches geometry as WKB and writes GeoParquet
through DuckDB (`openmapstack[geo]`), with the driver from
`openmapstack[postgis]`.

PostgreSQL has **no durable time travel**: `pg_export_snapshot()` lives only
as long as its transaction. The pin for a PostGIS source is therefore the
local snapshot; the connector records `pg_current_snapshot()` and the schema
digest beside it as retrieval metadata (`durable: false`), never as a pin.
Declaring `pin.class: backend_snapshot` for PostGIS is honest only when an
external mechanism (a logical replica frozen for the project, a `pg_dump`
retained under a stated policy) provides the retention you record.

### BigQuery

Declare `warehouse.project`, `warehouse.dataset`, and optionally
`warehouse.location`: unlike a DSN, the credential names no target.
`access.connection` resolves to a service-account key file
(`env:GOOGLE_APPLICATION_CREDENTIALS`) or, as `service:default`, to the
ambient default credentials. Install `openmapstack[bigquery]`.

BigQuery bills by bytes scanned, so **every statement is dry-run first** and
refused before execution when the estimate exceeds `--max-scan-bytes`
(`scan_limit_exceeded`); the executed job also carries
`maximum_bytes_billed`, so a table that grew since the dry run is refused by
the service rather than silently billed. The plan records what it would
scan under `plan.scan_bytes`.

**The estimate is not always available.** For a query over a table with a row
access policy, BigQuery returns no byte estimate at all — it will not say how
much it would read when some of that data is filtered from you. The
pre-execution check cannot run there: `plan.scan_bytes` is null,
`plan.scan_estimated` is false, the CLI warns, and `maximum_bytes_billed` on
the executed job is what bounds the cost instead. Do not read a missing
estimate as a cheap query.

Two BigQuery-specific traps:

- **`Table.num_rows` is not what your reader can see.** Discovery reports it
  as a row *estimate* and says so; row access policies are applied to
  queries, not to table metadata. Count with a query before claiming a
  number, and never present metadata counts as RLS-visible counts.
- **`GEOGRAPHY` has exactly one CRS.** Values are WGS84 and are written as
  EPSG:4326 (`OGC:CRS84`) GeoParquet. A `GEOGRAPHY` column needs no CRS
  guess and must not be reprojected on the way in.

Destination tables, scripting, and `EXPORT DATA` are unreachable: the query
policy accepts one `SELECT`, and the job configuration is the connector's.

### MotherDuck

Declare `warehouse.database` (the `md:` database) and reference the token as
`env:MOTHERDUCK_TOKEN`. Install `openmapstack[motherduck]`.

MotherDuck *is* DuckDB, so the connector reuses the `md:` protocol rather
than a second SQL dialect. The database is attached `READ_ONLY` where the
installed DuckDB supports it, and when it cannot be, discovery says so in a
note instead of implying an enforcement that is not there. Session setup —
`LOAD`, `ATTACH`, `USE`, the token — belongs to the connector and happens
before any analysis SQL exists; user SQL is a single `SELECT` and can never
`ATTACH`, `INSTALL`/`LOAD`, `CREATE SECRET`, `COPY` to a file, or run
DDL/DML.

One honest limitation: a MotherDuck session needs network access, so unlike
the local DuckDB connector it cannot run with `enable_external_access =
false` — and `allowed_directories` does nothing without that switch, which
DuckDB will not re-enable once a database is running. There is therefore no
session-level file confinement here: the query policy in rule 2 is what stops
a query reading a local file, and the token's own scope is what bounds the
rest. Use a token scoped to the database you are reading.

## Other backends

DuckDB, PostGIS, BigQuery and MotherDuck are verified. `warehouse.backend`
may name another system (`snowflake`, `databricks`, `redshift`, `athena`,
`iceberg`, `delta`), but the CLI refuses to connect to it
(`backend_unsupported`) rather than guessing its semantics. For those:

- pull the data with the vendor's tooling into `data/source/` and pin it as
  a `local_snapshot`, or
- use the backend's own snapshot/time-travel identity (Snowflake `AT
  (STATEMENT => ...)`, Iceberg/Delta snapshot ids) as a `backend_snapshot`,
  **recording the retention limit the vendor actually guarantees**
  (Snowflake Time Travel defaults to one day; BigQuery keeps seven), and
  expect `verify` to report `not_reproducible` once that passes.

The same caution applies to the verified cloud backends: BigQuery time
travel is seven days, which is a refresh window, not a reproducibility
mechanism. Pin the local snapshot.

Never approximate a pin by pasting the current date. The point of the pin
contract is that a reviewer can tell the difference.

## Clean rerun with warehouse sources

A clean rerun copies only `data/source/`, `data/overrides/`, the manifest,
and declared dependencies, and executes the pipeline with session/provider
environment variables removed. A pipeline that reads the warehouse live at
run time therefore fails the rerun unless the credential reference resolves
in the rerun environment — and if it does, the rerun proves only that the
warehouse still answers, not that it answers the same thing. Read from the
local snapshot in the pipeline; keep the query that produced it under
`warehouse.query_sha256` so the snapshot can be refreshed deliberately.
