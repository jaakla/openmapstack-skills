"""Safe, read-only connectors for user warehouse data (pilot).

The connector surface is deliberately small and defensive:

- **credentials by reference** -- ``access.connection`` names where the
  credential lives (``env:NAME``, ``service:NAME``, ``file:/abs/path``);
  the resolved value is used to open a session and is never recorded;
- **read-only discovery** -- a connector lists tables/files, geometry
  columns, SRIDs, and row estimates through a session that cannot write;
- **explicit approval** -- ``snapshot_source`` never materialises data into
  ``data/source/`` unless the caller passes ``approve=True``; without it the
  call is a dry run that reports the schema and row count it *would* copy;
- **limits** -- a statement timeout, a row cap, and a byte cap apply to
  every query; a query that exceeds any of them is refused, and a
  half-written file is removed;
- **only SELECT** -- one statement, no DML/DDL/COPY/ATTACH keywords, no
  statement separators, and no table function or bare path that would read a
  file or a URL of the query's own choosing;
- **scan limits** -- a backend that bills by bytes scanned (BigQuery) is
  dry-run first and refused before execution when the estimate exceeds
  ``max_scan_bytes``;
- **redaction** -- every message a connector emits passes through
  ``openmapstack.sources.redact``.

Four backends are implemented: ``duckdb`` for local files (GeoParquet,
GeoJSON, GeoPackage, FlatGeobuf, ``.duckdb`` databases), ``postgis`` for
PostgreSQL/PostGIS, ``bigquery``, and ``motherduck``. Other warehouses are
documented only where their behaviour has been verified; they are not
silently accepted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..integrity import sha256_file
from ..project import get_in, project_path
from ..sources import CONNECTION_REFERENCE_SCHEMES, redact

BACKENDS = ("duckdb", "postgis", "bigquery", "motherduck")

#: Table functions that read something the *query* names -- a local file, a
#: URL, or another database -- rather than the relation the connector exposed.
#: The local DuckDB connector also confines file access with
#: ``allowed_directories`` + ``enable_external_access = false``, but that pair
#: is unavailable to any backend that needs the network (MotherDuck reaches
#: its warehouse over it, and ``enable_external_access`` cannot be re-enabled
#: once a database is running). So the policy, not the session, is what has to
#: hold for those backends, and it refuses these before execution.
_EXTERNAL_READERS = re.compile(
    r"\b("
    r"read_csv|read_csv_auto|sniff_csv|read_parquet|parquet_scan|parquet_metadata|parquet_schema|"
    r"read_json|read_json_auto|read_ndjson|read_ndjson_auto|json_scan|read_xlsx|"
    r"st_read|st_read_meta|st_readosm|"
    r"delta_scan|iceberg_scan|iceberg_metadata|iceberg_snapshots|"
    r"postgres_scan|postgres_scan_pushdown|postgres_query|mysql_scan|mysql_query|"
    r"sqlite_scan|sqlite_query|external_query"
    r")\s*\(",
    re.IGNORECASE,
)

#: ``FROM 'some/path.parquet'`` and ``FROM 'https://...'``: DuckDB resolves a
#: bare string in table position as a file or URL, so it is the same hole
#: without a function name. Detected after string literals are masked, so a
#: literal that merely *contains* the word "from" cannot trip it.
_PATH_AS_TABLE = re.compile(r"\b(from|join)\s+''", re.IGNORECASE)

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|copy|grant|revoke|truncate|call|execute|"
    r"attach|detach|install|load|pragma|set|reset|vacuum|merge|into|import|export|checkpoint|"
    r"begin|commit|rollback|do|listen|notify|refresh|lock|security_invoker|pg_read_file|"
    r"read_text|read_blob|glob)\b",
    re.IGNORECASE,
)


class ConnectorError(Exception):
    """A connector refused or failed an operation. Messages are redacted."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(redact(message))
        self.code = code


class ConnectorUnavailable(ConnectorError):
    """The backend driver is not installed in this environment."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="driver_unavailable")


@dataclass(frozen=True)
class ConnectorLimits:
    timeout_s: float = 60.0
    max_rows: int = 100_000
    max_bytes: int = 256 * 1024 * 1024
    #: Bytes a metered backend may scan. Enforced *before* execution from a
    #: dry-run estimate, and passed to the backend as its own billing cap.
    #: Backends that do not meter scanned bytes ignore it.
    max_scan_bytes: int = 1024 * 1024 * 1024

    def validate(self) -> None:
        if self.timeout_s <= 0 or self.max_rows <= 0 or self.max_bytes <= 0 or self.max_scan_bytes <= 0:
            raise ConnectorError("limits must all be positive", code="limits_invalid")


@dataclass
class TableInfo:
    schema: str | None
    name: str
    geometry_column: str | None
    srid: int | None
    geometry_type: str | None
    row_estimate: int | None
    kind: str = "table"  # table | view | file

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "kind": self.kind,
            "geometry_column": self.geometry_column,
            "srid": self.srid,
            "geometry_type": self.geometry_type,
            "row_estimate": self.row_estimate,
        }


@dataclass
class Discovery:
    backend: str
    identity: dict[str, Any]
    tables: list[TableInfo] = field(default_factory=list)
    read_only: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "openmapstack-source-discovery/v1",
            "backend": self.backend,
            "identity": self.identity,
            "read_only": self.read_only,
            "tables": [table.to_dict() for table in self.tables],
            "notes": self.notes,
        }


@dataclass
class QueryPlan:
    """What a snapshot would copy, established without materialising it."""

    columns: list[dict[str, str]]
    row_count: int
    query_sha256: str
    schema_sha256: str
    backend_snapshot: dict[str, Any] | None = None
    #: Bytes the backend estimated it would scan, for backends that meter it.
    scan_bytes: int | None = None
    #: Whether a pre-execution scan estimate was available at all. A metered
    #: backend can decline to give one -- BigQuery does for a table with a row
    #: access policy -- and an unavailable estimate must not read as a cheap
    #: query. ``None`` here means the backend does not meter scanned bytes.
    scan_estimated: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "row_count": self.row_count,
            "query_sha256": self.query_sha256,
            "schema_sha256": self.schema_sha256,
            "backend_snapshot": self.backend_snapshot,
            "scan_bytes": self.scan_bytes,
            "scan_estimated": self.scan_estimated,
        }


def require_read_only_select(query: str) -> str:
    """Accept exactly one SELECT/WITH statement with no side-effect keywords.

    SQL line comments (``--``) are allowed: they are documentation, not
    statements, so they are removed before the policy checks and cannot hide
    or trigger a rejection.
    """
    if not isinstance(query, str) or not query.strip():
        raise ConnectorError("query must be a non-empty SELECT statement", code="query_rejected")
    text = query.strip().rstrip(";").strip()
    stripped = re.sub(r"'(?:[^']|'')*'", "''", text)  # ignore text inside string literals
    bare = re.sub(r"--[^\n]*", " ", stripped).strip()  # ignore line comments as well
    if ";" in bare:
        raise ConnectorError("query must be a single statement", code="query_rejected")
    if not re.match(r"(?is)^(select|with)\b", bare):
        raise ConnectorError("only SELECT (or WITH ... SELECT) queries are allowed", code="query_rejected")
    match = _FORBIDDEN_KEYWORDS.search(bare)
    if match:
        raise ConnectorError(f"query contains a forbidden keyword: {match.group(0).upper()}", code="query_rejected")
    match = _EXTERNAL_READERS.search(bare)
    if match:
        raise ConnectorError(
            f"query reads a source of its own choosing via {match.group(1).lower()}(); "
            "read the relations the connector exposed",
            code="query_rejected",
        )
    if _PATH_AS_TABLE.search(bare):
        raise ConnectorError(
            "query names a file or URL in table position; read the relations the connector exposed",
            code="query_rejected",
        )
    return text


def query_digest(query: str) -> str:
    canonical = " ".join(query.strip().rstrip(";").split())
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def schema_digest(columns: list[dict[str, str]]) -> str:
    canonical = json.dumps(columns, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_connection_reference(reference: object, *, environ: dict[str, str] | None = None) -> tuple[str, str]:
    """Resolve ``access.connection`` to ``(scheme, secret)``.

    The secret is returned for opening a session only; callers must never
    write it to a manifest, a log, or an evidence file.
    """
    environ = os.environ if environ is None else environ
    value = reference.get("ref") if isinstance(reference, dict) else reference
    if not isinstance(value, str) or ":" not in value:
        raise ConnectorError("access.connection must be a reference such as env:NAME", code="connection_reference_invalid")
    scheme, _, remainder = value.partition(":")
    remainder = remainder.strip()
    if scheme not in CONNECTION_REFERENCE_SCHEMES or not remainder:
        raise ConnectorError(f"unsupported connection reference scheme {scheme!r}", code="connection_reference_invalid")
    if scheme == "env":
        secret = environ.get(remainder)
        if not secret:
            raise ConnectorError(f"environment variable {remainder} is not set", code="connection_unresolved")
        return scheme, secret
    if scheme == "file":
        path = Path(remainder).expanduser()
        if not path.is_absolute():
            raise ConnectorError("file: connection references must be absolute paths outside the project", code="connection_reference_invalid")
        try:
            secret = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConnectorError(f"cannot read connection file: {type(exc).__name__}", code="connection_unresolved") from exc
        if not secret:
            raise ConnectorError("connection file is empty", code="connection_unresolved")
        return scheme, secret
    if scheme == "service":
        return scheme, f"service={remainder}"
    raise ConnectorError("keyring: references are not supported by the pilot connectors", code="connection_reference_invalid")


def load_connector(backend: str, connection: str, *, project_root: Path, warehouse: dict[str, Any] | None = None):
    """Build a connector for ``backend``.

    ``warehouse`` is the source's ``warehouse`` block. The cloud backends need
    it to know *what* to read -- a BigQuery dataset, a MotherDuck database --
    because unlike a DSN or a directory, their credential names no target.
    """
    warehouse = warehouse or {}
    if backend == "duckdb":
        from .duckdb_local import DuckDBLocalConnector

        return DuckDBLocalConnector(connection, project_root=project_root)
    if backend == "postgis":
        from .postgis import PostGISConnector

        return PostGISConnector(connection)
    if backend == "bigquery":
        from .bigquery import BigQueryConnector

        return BigQueryConnector(
            connection,
            project=_text(warehouse.get("project")),
            dataset=_text(warehouse.get("dataset")),
            location=_text(warehouse.get("location")),
        )
    if backend == "motherduck":
        from .motherduck import MotherDuckConnector

        return MotherDuckConnector(connection, database=_text(warehouse.get("database")))
    raise ConnectorError(
        f"backend {backend!r} is not a verified connector; supported: {list(BACKENDS)}",
        code="backend_unsupported",
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _source_block(manifest: dict[str, Any], source_key: str) -> dict[str, Any]:
    source = get_in(manifest, "sources", source_key)
    if not isinstance(source, dict):
        raise ConnectorError(f"source {source_key!r} is not declared", code="source_undeclared")
    return source


def connector_for_source(
    manifest: dict[str, Any],
    source_key: str,
    *,
    project_root: Path,
    environ: dict[str, str] | None = None,
):
    source = _source_block(manifest, source_key)
    warehouse = source.get("warehouse") if isinstance(source.get("warehouse"), dict) else {}
    backend = get_in(source, "warehouse", "backend")
    if not isinstance(backend, str):
        raise ConnectorError(f"source {source_key!r} declares no warehouse.backend", code="backend_undeclared")
    reference = get_in(source, "access", "connection")
    if backend == "duckdb" and reference is None:
        # Local files need no credential: the "connection" is the project's
        # own data/source directory.
        return load_connector(backend, "", project_root=project_root, warehouse=warehouse)
    _, secret = resolve_connection_reference(reference, environ=environ)
    return load_connector(backend, secret, project_root=project_root, warehouse=warehouse)


def discover_source(
    manifest: dict[str, Any],
    source_key: str,
    *,
    project_root: Path,
    limits: ConnectorLimits | None = None,
    environ: dict[str, str] | None = None,
) -> Discovery:
    limits = limits or ConnectorLimits()
    limits.validate()
    connector = connector_for_source(manifest, source_key, project_root=project_root, environ=environ)
    return connector.discover(limits)


def snapshot_source(
    manifest: dict[str, Any],
    source_key: str,
    query: str,
    destination: str,
    *,
    project_root: Path,
    approve: bool = False,
    limits: ConnectorLimits | None = None,
    environ: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Plan, and with ``approve`` materialise, a query snapshot under data/source/.

    Returns a record with the plan, and when materialised the pin block and
    warehouse metadata to place in the manifest. Nothing is written without
    approval; a file that breaches ``limits`` is removed before returning.
    """
    limits = limits or ConnectorLimits()
    limits.validate()
    query = require_read_only_select(query)
    target = project_path(project_root, destination)
    if target is None or not destination.replace("\\", "/").startswith("data/source/"):
        raise ConnectorError("snapshot destination must be a project-relative path under data/source/", code="destination_invalid")
    if target.suffix.lower() != ".parquet":
        raise ConnectorError("snapshots are materialised as GeoParquet; use a .parquet destination", code="destination_invalid")
    source = _source_block(manifest, source_key)
    connector = connector_for_source(manifest, source_key, project_root=project_root, environ=environ)
    plan = connector.plan(query, limits)
    if plan.row_count > limits.max_rows:
        raise ConnectorError(
            f"query would return {plan.row_count} rows, above max_rows={limits.max_rows}",
            code="row_limit_exceeded",
        )
    record: dict[str, Any] = {
        "schema": "openmapstack-source-snapshot/v1",
        "source": source_key,
        "backend": connector.backend,
        "destination": destination,
        "approved": bool(approve),
        "materialized": False,
        "plan": plan.to_dict(),
        "limits": {"timeout_s": limits.timeout_s, "max_rows": limits.max_rows, "max_bytes": limits.max_bytes},
    }
    if not approve:
        record["note"] = "dry run: nothing was written; pass approve=True (--approve) to materialise"
        return record

    if target.exists():
        raise ConnectorError(
            f"{destination} already exists; sources are immutable, choose a new snapshot name",
            code="destination_exists",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    try:
        rows = connector.materialize(query, temporary, limits)
        size = temporary.stat().st_size
        if size > limits.max_bytes:
            raise ConnectorError(f"snapshot is {size} bytes, above max_bytes={limits.max_bytes}", code="byte_limit_exceeded")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    captured_at = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    digest = sha256_file(target)
    warehouse = dict(source.get("warehouse") or {})
    warehouse.update({"query_sha256": plan.query_sha256, "schema_sha256": plan.schema_sha256})
    warehouse.update(connector.identity_for_manifest())
    record.update(
        {
            "materialized": True,
            "rows": rows,
            "bytes": target.stat().st_size,
            "sha256": digest,
            "pin": {"class": "local_snapshot", "path": destination, "sha256": digest, "captured_at": captured_at},
            "warehouse": warehouse,
            "access": {"retrieved_at": captured_at, "downloaded_at": captured_at},
        }
    )
    if plan.backend_snapshot:
        record["backend_snapshot"] = plan.backend_snapshot
    return record


def apply_snapshot_to_manifest(manifest: dict[str, Any], source_key: str, record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``manifest`` with the snapshot's pin and metadata applied."""
    import copy

    updated = copy.deepcopy(manifest)
    source = _source_block(updated, source_key)
    if not record.get("materialized"):
        raise ConnectorError("only a materialised snapshot can be written to the manifest", code="not_materialized")
    source["pin"] = record["pin"]
    source["warehouse"] = record["warehouse"]
    access = source.setdefault("access", {})
    access.update(record["access"])
    file_block = access.setdefault("file", {})
    file_block.update({"name": Path(record["destination"]).name, "format": "GeoParquet", "row_count": record["rows"], "size_bytes": record["bytes"]})
    return updated
