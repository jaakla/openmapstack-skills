"""BigQuery connector: read-only discovery, dry-run scan guard, pinned snapshots.

BigQuery bills by bytes scanned, so a snapshot here has one guard the local
backends do not need: every statement is **dry-run first**, and the estimate
it returns is checked against ``limits.max_scan_bytes`` *before* anything is
executed. The executed job also carries ``maximum_bytes_billed``, so a table
that grows between the dry run and the run is refused by the service rather
than silently billed.

Three further rules follow from the platform:

- **metadata row counts are not RLS-visible row counts.** ``Table.num_rows``
  ignores row access policies, so discovery reports it as an estimate and
  says so in a note; only a counted query speaks for what the reader sees.
- **GEOGRAPHY is always WGS84.** Values arrive as WKT and are written as
  EPSG:4326 GeoParquet, which is the one CRS BigQuery geography has.
- **the job configuration is the connector's, not the query's.** Destination
  tables, scripting and ``EXPORT DATA`` are unreachable from user SQL because
  ``require_read_only_select`` accepts a single SELECT and the connector never
  sets a destination.

``google-cloud-bigquery`` is imported lazily and its absence is reported as
``driver_unavailable``. A ``client`` may be injected for tests.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import (
    ConnectorError,
    ConnectorLimits,
    ConnectorUnavailable,
    Discovery,
    QueryPlan,
    TableInfo,
    query_digest,
    schema_digest,
)

GEOGRAPHY_SRID = 4326
_ROW_COUNT_NOTE = (
    "row_estimate is table metadata (Table.num_rows); it ignores row access policies, "
    "so it is not the number of rows this reader can see"
)


def _default_client(credentials: str, project: str | None, location: str | None) -> Any:
    """Build a client from a service-account key file, or from ADC.

    ``credentials`` is whatever ``access.connection`` resolved to: the value
    of ``GOOGLE_APPLICATION_CREDENTIALS`` (a key-file path), or the
    ``service=NAME`` marker that means "use the ambient default credentials".
    """
    try:
        from google.cloud import bigquery  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConnectorUnavailable(
            "the bigquery connector requires google-cloud-bigquery (pip install 'openmapstack[bigquery]')"
        ) from exc
    try:
        if credentials.startswith("service="):
            return bigquery.Client(project=project, location=location)
        return bigquery.Client.from_service_account_json(credentials, project=project, location=location)
    except ConnectorError:
        raise
    except Exception as exc:  # noqa: BLE001 - client errors may quote the key path
        raise ConnectorError(f"cannot open a BigQuery client: {type(exc).__name__}", code="connection_failed") from exc


def _default_job_config(**kwargs: Any) -> Any:
    from google.cloud import bigquery  # type: ignore[import-not-found]

    return bigquery.QueryJobConfig(**kwargs)


class BigQueryConnector:
    backend = "bigquery"

    def __init__(
        self,
        credentials: str,
        *,
        project: str | None = None,
        dataset: str | None = None,
        location: str | None = None,
        client: Any | None = None,
        job_config: Callable[..., Any] | None = None,
    ) -> None:
        self._credentials = credentials
        self._project = project
        self._dataset = dataset
        self._location = location
        self._client = client
        self._job_config = job_config or _default_job_config
        self._notes: list[str] = []

    # -- sessions ---------------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _default_client(self._credentials, self._project, self._location)
        if self._project is None:
            self._project = getattr(self._client, "project", None)
        return self._client

    def identity_for_manifest(self) -> dict[str, Any]:
        identity: dict[str, Any] = {"backend": "bigquery"}
        for key, value in (("project", self._project), ("dataset", self._dataset), ("location", self._location)):
            if value:
                identity[key] = value
        return identity

    def _dataset_reference(self) -> str:
        if not self._dataset:
            raise ConnectorError(
                "a bigquery source must declare warehouse.dataset (the dataset to discover)",
                code="dataset_undeclared",
            )
        project = self._project or getattr(self.client, "project", None)
        return f"{project}.{self._dataset}" if project else self._dataset

    # -- discovery --------------------------------------------------------------

    def discover(self, limits: ConnectorLimits) -> Discovery:
        # A manifest that names no dataset is wrong whether or not the driver
        # is installed, so it is reported before any client is built.
        if not self._dataset:
            raise ConnectorError(
                "a bigquery source must declare warehouse.dataset (the dataset to discover)",
                code="dataset_undeclared",
            )
        client = self.client
        reference = self._dataset_reference()
        try:
            listed = list(client.list_tables(reference, timeout=limits.timeout_s))
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"cannot list dataset {self._dataset!r}: {type(exc).__name__}", code="discovery_failed") from exc
        tables: list[TableInfo] = []
        for item in listed:
            name = str(getattr(item, "table_id", item))
            try:
                table = client.get_table(f"{reference}.{name}", timeout=limits.timeout_s)
            except Exception as exc:  # noqa: BLE001 - an inaccessible table stays inaccessible
                self._note(f"{name}: not accessible to this reader ({type(exc).__name__})")
                continue
            tables.append(self._describe(table, name))
        notes = [_ROW_COUNT_NOTE, *self._notes]
        identity = {"project": self._project, "dataset": self._dataset, "location": self._location}
        # Every session this connector opens is read-only: it issues a single
        # SELECT with no destination table, and never a DDL/DML job.
        return Discovery("bigquery", identity, tables, read_only=True, notes=notes)

    def _describe(self, table: Any, name: str) -> TableInfo:
        fields = list(getattr(table, "schema", None) or [])
        geography = next(
            (str(field.name) for field in fields if str(getattr(field, "field_type", "")).upper() == "GEOGRAPHY"),
            None,
        )
        kind = "view" if "VIEW" in str(getattr(table, "table_type", "TABLE")).upper() else "table"
        rows = getattr(table, "num_rows", None)
        info = TableInfo(
            self._dataset,
            name,
            geography,
            GEOGRAPHY_SRID if geography else None,
            "GEOGRAPHY" if geography else None,
            int(rows) if rows is not None else None,
            kind=kind,
        )
        partitioning = _partitioning(table)
        if partitioning:
            self._note(f"{name}: {partitioning}")
        return info

    def _note(self, note: str) -> None:
        if note not in self._notes:
            self._notes.append(note)

    # -- queries ----------------------------------------------------------------

    def _run(self, sql: str, limits: ConnectorLimits, *, dry_run: bool) -> Any:
        config = (
            self._job_config(dry_run=True, use_query_cache=False)
            if dry_run
            else self._job_config(use_query_cache=False, maximum_bytes_billed=int(limits.max_scan_bytes))
        )
        try:
            return self.client.query(sql, job_config=config)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"query failed: {type(exc).__name__}", code="query_failed") from exc

    def _guarded_dry_run(self, sql: str, limits: ConnectorLimits) -> tuple[Any, int]:
        """Dry-run ``sql`` and refuse it if it would scan too much.

        Nothing is executed and nothing is billed by a dry run, so this is the
        only place a scan limit can be enforced *before* the cost is incurred.
        """
        job = self._run(sql, limits, dry_run=True)
        scanned = getattr(job, "total_bytes_processed", None)
        scanned = int(scanned) if scanned is not None else 0
        if scanned > limits.max_scan_bytes:
            raise ConnectorError(
                f"query would scan {scanned} bytes, above max_scan_bytes={limits.max_scan_bytes}",
                code="scan_limit_exceeded",
            )
        return job, scanned

    def plan(self, query: str, limits: ConnectorLimits) -> QueryPlan:
        job, scanned = self._guarded_dry_run(query, limits)
        columns = _columns_from(getattr(job, "schema", None) or [])
        if not columns:
            raise ConnectorError("the dry run returned no result schema", code="query_failed")
        count_sql = f"SELECT count(*) AS row_count FROM (\n{query}\n) AS q"
        _, count_scanned = self._guarded_dry_run(count_sql, limits)
        count_job = self._run(count_sql, limits, dry_run=False)
        try:
            rows = list(count_job.result())
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"row count failed: {type(exc).__name__}", code="query_failed") from exc
        if not rows:
            raise ConnectorError("row count returned no rows", code="query_failed")
        return QueryPlan(
            columns,
            int(_value(rows[0], 0, "row_count")),
            query_digest(query),
            schema_digest(columns),
            scan_bytes=scanned + count_scanned,
        )

    def materialize(self, query: str, destination: Path, limits: ConnectorLimits) -> int:
        from ..checks.spatial import connect_spatial

        duck = connect_spatial()
        if duck is None:
            raise ConnectorUnavailable("materialising GeoParquet requires duckdb with Spatial (pip install 'openmapstack[geo]')")
        job, _ = self._guarded_dry_run(query, limits)
        columns = _columns_from(getattr(job, "schema", None) or [])
        geography_columns = [column["name"] for column in columns if column["type"] == "GEOGRAPHY"]
        executed = self._run(query, limits, dry_run=False)
        try:
            result = executed.result(max_results=int(limits.max_rows))
            rows = [tuple(_value(row, index, column["name"]) for index, column in enumerate(columns)) for row in result]
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"snapshot failed: {type(exc).__name__}", code="query_failed") from exc
        try:
            _write_parquet(duck, destination, columns, geography_columns, rows)
        finally:
            duck.close()
        return len(rows)


# -- helpers -------------------------------------------------------------------


def _partitioning(table: Any) -> str | None:
    time_partitioning = getattr(table, "time_partitioning", None)
    if time_partitioning is not None:
        field = getattr(time_partitioning, "field", None) or "_PARTITIONTIME"
        return f"partitioned by {field} ({getattr(time_partitioning, 'type_', 'DAY')})"
    range_partitioning = getattr(table, "range_partitioning", None)
    if range_partitioning is not None:
        return f"range-partitioned by {getattr(range_partitioning, 'field', '?')}"
    return None


def _columns_from(fields: Any) -> list[dict[str, str]]:
    return [
        {"name": str(field.name), "type": str(getattr(field, "field_type", "STRING")).upper()}
        for field in fields
    ]


def _value(row: Any, index: int, name: str) -> Any:
    """Read a cell from a BigQuery ``Row``, a mapping, or a plain sequence."""
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        pass
    try:
        return row[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise ConnectorError(f"result row is missing column {name!r}", code="query_failed") from exc


_DUCK_TYPES = {
    "INT64": "BIGINT", "INTEGER": "BIGINT", "FLOAT64": "DOUBLE", "FLOAT": "DOUBLE",
    "BOOL": "BOOLEAN", "BOOLEAN": "BOOLEAN", "DATE": "DATE", "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMPTZ", "TIME": "TIME", "BYTES": "BLOB", "JSON": "JSON",
}


def _write_parquet(duck, destination: Path, columns, geography_columns, rows) -> None:
    """Stage the rows in DuckDB and write GeoParquet.

    ``NUMERIC``/``BIGNUMERIC`` are staged as exact DECIMAL where BigQuery's
    fixed scale allows it: NUMERIC is DECIMAL(38, 9) by definition, and
    BIGNUMERIC exceeds DuckDB's DECIMAL(38), so it keeps its exact text
    rather than rounding through DOUBLE under a hash that pins it.
    """
    definitions = []
    text_columns: set[int] = set()
    for index, column in enumerate(columns):
        name = column["name"].replace('"', '""')
        if column["name"] in geography_columns:
            definitions.append(f'"{name}" VARCHAR')  # WKT, converted on the way out
        elif column["type"] == "NUMERIC":
            definitions.append(f'"{name}" DECIMAL(38, 9)')
        elif column["type"] == "BIGNUMERIC":
            text_columns.add(index)
            definitions.append(f'"{name}" VARCHAR')
        else:
            definitions.append(f'"{name}" {_DUCK_TYPES.get(column["type"], "VARCHAR")}')
    duck.execute(f"CREATE TABLE staging ({', '.join(definitions)})")
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        duck.executemany(
            f"INSERT INTO staging VALUES ({placeholders})",
            [tuple(_plain(value, exact_text=index in text_columns) for index, value in enumerate(row)) for row in rows],
        )
    selected = []
    for column in columns:
        name = column["name"].replace('"', '""')
        if column["name"] in geography_columns:
            expression = f'ST_GeomFromText("{name}")'
            try:
                duck.execute(f"SELECT ST_SetSRID(ST_GeomFromText('POINT(0 0)'), {GEOGRAPHY_SRID})")
                expression = f'ST_SetSRID(ST_GeomFromText("{name}"), {GEOGRAPHY_SRID})'
            except Exception:  # noqa: BLE001 - older Spatial without CRS support
                pass
            selected.append(f'{expression} AS "{name}"')
        else:
            selected.append(f'"{name}"')
    target = destination.as_posix().replace("'", "''")
    duck.execute(f"COPY (SELECT {', '.join(selected)} FROM staging) TO '{target}' (FORMAT PARQUET)")


def _plain(value: Any, *, exact_text: bool = False) -> Any:
    from decimal import Decimal

    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, Decimal):
        if exact_text or not value.is_finite():
            return format(value, "f") if value.is_finite() else str(value)
        return value
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, sort_keys=True, default=str)
    return value
