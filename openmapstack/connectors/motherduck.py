"""MotherDuck connector: the `md:` protocol, used read-only.

MotherDuck *is* DuckDB, so this connector reuses the ``md:`` protocol rather
than inventing another SQL dialect, and materialises GeoParquet with the same
``COPY ... (FORMAT PARQUET)`` the local DuckDB connector uses.

The security split is the point:

- **session setup is the connector's.** ``ATTACH``/``LOAD``/``USE`` and the
  token are issued here, once, before any user SQL exists. The database is
  attached ``READ_ONLY`` when the installed DuckDB supports it, and when it
  does not, the gap is recorded in the discovery notes rather than hidden.
- **analysis SQL is only a SELECT.** ``require_read_only_select`` runs before
  anything reaches this connector, so user SQL can never ``ATTACH`` another
  database, ``INSTALL``/``LOAD`` an extension, ``CREATE SECRET``, ``COPY`` to
  a file, or run DDL/DML.
- **network access stays on, deliberately.** Unlike the local-file connector
  this one cannot ``SET enable_external_access = false`` — that is how it
  reaches MotherDuck at all — so confinement rests on the query policy and on
  the token's own permissions, and discovery says so.

The token is resolved from ``access.connection`` (``env:MOTHERDUCK_TOKEN``)
and is never written to a manifest, a note, or an error.
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
from .duckdb_local import _Timeout, _escape

ALIAS = "warehouse"
_NETWORK_NOTE = (
    "a MotherDuck session needs network access, so file access is not confined by "
    "enable_external_access; user SQL is restricted to a single SELECT instead"
)
_COUNT_NOTE = "row_estimate is a counted SELECT through this token; it reflects what this token may read"


def _reachable_databases(connection: Any) -> list[str]:
    """Database names this session can see, for a failed-attach message.

    Best effort: a session too broken to answer gives an empty list rather
    than replacing the original failure with a second one.
    """
    try:
        rows = connection.execute(
            "SELECT database_name FROM duckdb_databases() "
            "WHERE database_name NOT IN ('memory', 'system', 'temp') ORDER BY 1"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    # Sorted here rather than trusting ORDER BY: the message is compared in
    # tests and read by people, and should not vary with backend ordering.
    return sorted(str(row[0]) for row in rows)


def _default_connect(token: str) -> Any:
    """Open a bare DuckDB session. The token is applied later, in ``_session``.

    It cannot be passed as connect-time ``config``: ``motherduck_token`` is
    registered *by* the MotherDuck extension, and connect-time options are
    validated before any extension loads, so DuckDB answers
    ``The following options were not recognized: motherduck_token``. The
    working order is LOAD, then SET, then ATTACH.
    """
    from ..checks.spatial import _connection_config

    try:
        import duckdb  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConnectorUnavailable(
            "the motherduck connector requires duckdb (pip install 'openmapstack[motherduck]')"
        ) from exc
    try:
        return duckdb.connect(config=dict(_connection_config()))
    except ConnectorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(f"cannot open a DuckDB session: {type(exc).__name__}", code="connection_failed") from exc


class MotherDuckConnector:
    backend = "motherduck"

    def __init__(
        self,
        token: str,
        *,
        database: str | None = None,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self._token = token
        self._database = database
        self._connect = connect
        self._notes: list[str] = []
        self._read_only = True

    # -- sessions ---------------------------------------------------------------

    def _note(self, note: str) -> None:
        if note not in self._notes:
            self._notes.append(note)

    def _session(self) -> Any:
        if not self._database:
            raise ConnectorError(
                "a motherduck source must declare warehouse.database (the md: database to read)",
                code="database_undeclared",
            )
        connect = self._connect or _default_connect
        connection = connect(self._token)
        try:
            connection.execute("LOAD motherduck")
        except Exception as exc:  # noqa: BLE001
            connection.close()
            raise ConnectorUnavailable(
                "this DuckDB build has no MotherDuck extension available offline; "
                "install it before running the connector (provision.py does, this does not: "
                "a connector never downloads an extension)"
            ) from exc
        # Only now does `motherduck_token` exist as an option. SET takes no
        # bound parameter, so the value is quote-escaped into the statement;
        # any error from it is wrapped so the token cannot reach a message
        # unredacted.
        try:
            connection.execute(f"SET motherduck_token = '{_escape(self._token)}'")
        except Exception as exc:  # noqa: BLE001
            connection.close()
            raise ConnectorError(
                f"MotherDuck rejected the access token: {type(exc).__name__}", code="connection_failed"
            ) from exc
        try:
            connection.execute("LOAD spatial")
        except Exception:  # noqa: BLE001 - geometry columns then read as their raw type
            self._note("DuckDB Spatial is not loaded; geometry columns are reported as their stored type")
        target = _escape(f"md:{self._database}")
        try:
            connection.execute(f"ATTACH '{target}' AS {ALIAS} (READ_ONLY)")
            self._read_only = True
        except Exception:  # noqa: BLE001 - older DuckDB/MotherDuck without READ_ONLY attach
            try:
                connection.execute(f"ATTACH '{target}' AS {ALIAS}")
            except Exception as exc:  # noqa: BLE001
                reachable = _reachable_databases(connection)
                connection.close()
                # A failed attach cannot distinguish "wrong name" from "right
                # name, wrong account" on its own, and the token is the one
                # thing that must not appear in the message. The database
                # names this token can actually see answer it immediately, and
                # a database name is not a secret.
                detail = (
                    f"; this token can reach: {', '.join(reachable)}"
                    if reachable
                    else "; this token can reach no databases at all"
                )
                raise ConnectorError(
                    f"cannot attach md:{self._database}: {type(exc).__name__}{detail}",
                    code="connection_failed",
                ) from exc
            self._read_only = False
            self._note(
                "this DuckDB could not ATTACH the database READ_ONLY; read-only behaviour rests on "
                "the token's permissions and on the single-SELECT query policy"
            )
        try:
            connection.execute(f"USE {ALIAS}")
        except Exception as exc:  # noqa: BLE001
            connection.close()
            raise ConnectorError(f"cannot use md:{self._database}: {type(exc).__name__}", code="connection_failed") from exc
        self._note(_NETWORK_NOTE)
        return connection

    def identity_for_manifest(self) -> dict[str, Any]:
        identity: dict[str, Any] = {"backend": "motherduck"}
        if self._database:
            identity["database"] = self._database
        return identity

    # -- discovery --------------------------------------------------------------

    def discover(self, limits: ConnectorLimits) -> Discovery:
        connection = self._session()
        tables: list[TableInfo] = []
        try:
            with _Timeout(connection, limits.timeout_s):
                listed = connection.execute(
                    "SELECT table_schema, table_name, table_type FROM information_schema.tables "
                    f"WHERE table_catalog = '{ALIAS}' ORDER BY 1, 2"
                ).fetchall()
                for schema, name, table_type in listed:
                    tables.append(self._describe(connection, str(schema), str(name), str(table_type)))
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"discovery failed: {type(exc).__name__}", code="discovery_failed") from exc
        finally:
            connection.close()
        notes = [_COUNT_NOTE, *self._notes]
        return Discovery("motherduck", {"database": self._database}, tables, read_only=self._read_only, notes=notes)

    def _describe(self, connection, schema: str, name: str, table_type: str) -> TableInfo:
        columns = connection.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_catalog = '{ALIAS}' AND table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [schema, name],
        ).fetchall()
        geometry = next((str(column) for column, type_name in columns if str(type_name).upper() == "GEOMETRY"), None)
        quoted = f'"{schema.replace(chr(34), chr(34) * 2)}"."{name.replace(chr(34), chr(34) * 2)}"'
        try:
            estimate = int(connection.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])
        except Exception as exc:  # noqa: BLE001 - an inaccessible relation stays inaccessible
            self._note(f"{schema}.{name}: not readable by this token ({type(exc).__name__})")
            estimate = None
        return TableInfo(
            schema,
            name,
            geometry,
            None,
            None,
            estimate,
            kind="view" if "VIEW" in table_type.upper() else "table",
        )

    # -- queries ----------------------------------------------------------------

    def plan(self, query: str, limits: ConnectorLimits) -> QueryPlan:
        connection = self._session()
        try:
            with _Timeout(connection, limits.timeout_s) as timeout:
                try:
                    described = connection.execute(f"DESCRIBE SELECT * FROM ({query}) AS q").fetchall()
                    count = connection.execute(f"SELECT count(*) FROM ({query}) AS q").fetchone()[0]
                except Exception as exc:  # noqa: BLE001
                    if timeout.fired:
                        raise ConnectorError(f"query exceeded timeout_s={limits.timeout_s}", code="timeout") from exc
                    raise ConnectorError(f"query failed: {type(exc).__name__}", code="query_failed") from exc
        finally:
            connection.close()
        columns = [{"name": str(name), "type": str(type_name)} for name, type_name, *_ in described]
        return QueryPlan(columns, int(count), query_digest(query), schema_digest(columns))

    def materialize(self, query: str, destination: Path, limits: ConnectorLimits) -> int:
        connection = self._session()
        target = _escape(destination.as_posix())
        try:
            with _Timeout(connection, limits.timeout_s) as timeout:
                try:
                    connection.execute(
                        f"COPY (SELECT * FROM ({query}) AS q LIMIT {int(limits.max_rows)}) "
                        f"TO '{target}' (FORMAT PARQUET)"
                    )
                    rows = connection.execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()[0]
                except Exception as exc:  # noqa: BLE001
                    if timeout.fired:
                        raise ConnectorError(f"query exceeded timeout_s={limits.timeout_s}", code="timeout") from exc
                    raise ConnectorError(f"snapshot failed: {type(exc).__name__}", code="query_failed") from exc
        finally:
            connection.close()
        return int(rows)
