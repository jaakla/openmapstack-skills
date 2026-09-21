"""BigQuery and MotherDuck connectors: policy, guards, normalisation, redaction.

Neither backend is contacted. BigQuery is driven through a fake client that
records every job it is handed, which is what makes the dry-run-before-execute
ordering and the scan guard observable. MotherDuck genuinely executes: the
injected session is a local DuckDB with an attached in-memory catalog named
like the `md:` database, so discovery, planning and materialisation run the
real statements the connector issues.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from openmapstack.checks.spatial import connect_spatial
from openmapstack.connectors import (
    BACKENDS,
    ConnectorError,
    ConnectorLimits,
    ConnectorUnavailable,
    load_connector,
)
from openmapstack.connectors.bigquery import BigQueryConnector
from openmapstack.connectors.motherduck import MotherDuckConnector
from tests.evals.helpers import make_workspace

DUCKDB_AVAILABLE = connect_spatial() is not None

# Live canary configuration. Absent locally and on ordinary PRs, where these
# classes skip; the cloud-canary workflow sets them and reports a missing
# secret as not_testable rather than as a pass.
LIVE_BIGQUERY_PROJECT = os.environ.get("OPENMAPSTACK_TEST_BIGQUERY_PROJECT", "")
LIVE_BIGQUERY_DATASET = os.environ.get("OPENMAPSTACK_TEST_BIGQUERY_DATASET", "")
LIVE_BIGQUERY_TABLE = os.environ.get("OPENMAPSTACK_TEST_BIGQUERY_TABLE", "zone_daily_demand")
LIVE_MOTHERDUCK_TOKEN = os.environ.get("OPENMAPSTACK_TEST_MOTHERDUCK_TOKEN", "")
LIVE_MOTHERDUCK_DATABASE = os.environ.get("OPENMAPSTACK_TEST_MOTHERDUCK_DATABASE", "")


# -- BigQuery doubles ----------------------------------------------------------


class _Field:
    def __init__(self, name: str, field_type: str) -> None:
        self.name = name
        self.field_type = field_type


class _Table:
    def __init__(self, fields, num_rows=None, table_type="TABLE", partition_field=None) -> None:
        self.schema = [_Field(name, type_name) for name, type_name in fields]
        self.num_rows = num_rows
        self.table_type = table_type
        self.time_partitioning = _Partitioning(partition_field) if partition_field else None
        self.range_partitioning = None


class _Partitioning:
    def __init__(self, field: str) -> None:
        self.field = field
        self.type_ = "DAY"


class _Job:
    def __init__(self, schema=None, rows=(), total_bytes_processed=0) -> None:
        self.schema = [_Field(name, type_name) for name, type_name in (schema or [])]
        self.total_bytes_processed = total_bytes_processed
        self._rows = list(rows)

    def result(self, max_results=None):
        return self._rows if max_results is None else self._rows[:max_results]


class _FakeBigQueryClient:
    """Answers the calls the connector makes, and records the jobs it runs."""

    def __init__(self, tables=None, jobs=None, project="northstar-demo") -> None:
        self.project = project
        self._tables = tables or {}
        self._jobs = jobs or {}
        self.calls: list[tuple[str, dict]] = []
        self.timeouts: list[float | None] = []

    def list_tables(self, reference, timeout=None):
        self.timeouts.append(timeout)
        return [_Listed(name) for name in self._tables]

    def get_table(self, reference, timeout=None):
        self.timeouts.append(timeout)
        name = str(reference).rsplit(".", 1)[-1]
        entry = self._tables[name]
        if isinstance(entry, Exception):
            raise entry
        return entry

    def query(self, sql, job_config=None):
        self.calls.append((sql, dict(job_config or {})))
        for pattern, job in self._jobs.items():
            if pattern in sql:
                return job
        raise AssertionError(f"unexpected query: {sql}")


class _Listed:
    def __init__(self, table_id: str) -> None:
        self.table_id = table_id


def _bigquery(tables=None, jobs=None, **kwargs) -> BigQueryConnector:
    return BigQueryConnector(
        "service=default",
        project="northstar-demo",
        dataset=kwargs.pop("dataset", "northstar_analytics"),
        client=_FakeBigQueryClient(tables, jobs),
        job_config=dict,
        **kwargs,
    )


class BigQueryDiscoveryTests(unittest.TestCase):
    def test_discovery_reports_geography_partitioning_and_the_row_count_caveat(self) -> None:
        connector = _bigquery(
            tables={
                "trip_events": _Table(
                    [("trip_id", "STRING"), ("pickup_point", "GEOGRAPHY"), ("fare", "NUMERIC")],
                    num_rows=64,
                    partition_field="pickup_date",
                ),
                "zone_daily_demand": _Table([("taxi_zone_id", "INT64")], num_rows=8, table_type="VIEW"),
            }
        )
        discovery = connector.discover(ConnectorLimits())
        self.assertEqual(discovery.backend, "bigquery")
        self.assertTrue(discovery.read_only)
        by_name = {table.name: table for table in discovery.tables}
        self.assertEqual(by_name["trip_events"].geometry_column, "pickup_point")
        self.assertEqual(by_name["trip_events"].srid, 4326)
        self.assertEqual(by_name["trip_events"].row_estimate, 64)
        self.assertEqual(by_name["zone_daily_demand"].kind, "view")
        self.assertIsNone(by_name["zone_daily_demand"].geometry_column)
        joined = " | ".join(discovery.notes)
        self.assertIn("ignores row access policies", joined)
        self.assertIn("partitioned by pickup_date", joined)
        self.assertEqual(set(connector.client.timeouts), {ConnectorLimits().timeout_s})

    def test_an_inaccessible_table_is_reported_not_invented(self) -> None:
        connector = _bigquery(
            tables={
                "zone_daily_demand": _Table([("taxi_zone_id", "INT64")], num_rows=8),
                "restricted_costs": PermissionError("denied"),
            }
        )
        discovery = connector.discover(ConnectorLimits())
        self.assertEqual([table.name for table in discovery.tables], ["zone_daily_demand"])
        self.assertTrue(any("restricted_costs: not accessible" in note for note in discovery.notes))

    def test_a_missing_dataset_is_a_manifest_error_before_any_client_call(self) -> None:
        connector = BigQueryConnector("service=default", project="p", dataset=None, client=None, job_config=dict)
        with self.assertRaises(ConnectorError) as caught:
            connector.discover(ConnectorLimits())
        self.assertEqual(caught.exception.code, "dataset_undeclared")


class BigQueryScanGuardTests(unittest.TestCase):
    """The guard's whole value is that it refuses *before* the bytes are billed."""

    def _jobs(self, scanned: int):
        return {
            "SELECT count(*)": _Job(schema=[("row_count", "INT64")], rows=[{"row_count": 3}], total_bytes_processed=16),
            "FROM northstar_analytics.zone_daily_demand": _Job(
                schema=[("taxi_zone_id", "INT64"), ("trips", "INT64")],
                rows=[(1, 10), (2, 20), (3, 30)],
                total_bytes_processed=scanned,
            ),
        }

    QUERY = "SELECT taxi_zone_id, trips FROM northstar_analytics.zone_daily_demand"

    def test_an_oversized_query_is_refused_and_never_executed(self) -> None:
        connector = _bigquery(jobs=self._jobs(5_000))
        with self.assertRaises(ConnectorError) as caught:
            connector.plan(self.QUERY, ConnectorLimits(max_scan_bytes=1_000))
        self.assertEqual(caught.exception.code, "scan_limit_exceeded")
        self.assertIn("5000 bytes", str(caught.exception))
        calls = connector.client.calls
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1]["dry_run"], "the refusal must come from a dry run, not an executed job")

    def test_a_permitted_query_is_dry_run_first_and_billed_against_the_cap(self) -> None:
        connector = _bigquery(jobs=self._jobs(400))
        plan = connector.plan(self.QUERY, ConnectorLimits(max_scan_bytes=1_000))
        self.assertEqual(plan.row_count, 3)
        self.assertEqual([column["name"] for column in plan.columns], ["taxi_zone_id", "trips"])
        self.assertEqual(plan.scan_bytes, 416)
        self.assertTrue(plan.query_sha256.startswith("sha256:"))
        modes = [(call[1].get("dry_run", False), call[1].get("maximum_bytes_billed")) for call in connector.client.calls]
        self.assertEqual(modes[0], (True, None), "the user query is dry-run before anything runs")
        self.assertTrue(any(billed == 1_000 for _, billed in modes), "executed jobs carry maximum_bytes_billed")
        self.assertFalse(any(call[1].get("use_query_cache", True) for call in connector.client.calls))

    def test_the_count_query_is_guarded_too(self) -> None:
        jobs = self._jobs(100)
        jobs["SELECT count(*)"] = _Job(schema=[("row_count", "INT64")], rows=[{"row_count": 3}], total_bytes_processed=9_999)
        connector = _bigquery(jobs=jobs)
        with self.assertRaises(ConnectorError) as caught:
            connector.plan(self.QUERY, ConnectorLimits(max_scan_bytes=1_000))
        self.assertEqual(caught.exception.code, "scan_limit_exceeded")
        self.assertTrue(all(call[1].get("dry_run") for call in connector.client.calls))


@unittest.skipUnless(DUCKDB_AVAILABLE, "DuckDB Spatial is not available")
class BigQueryMaterialisationTests(unittest.TestCase):
    def test_geography_is_written_as_epsg_4326_geoparquet(self) -> None:
        query = "SELECT taxi_zone_id, centroid FROM northstar_analytics.zone_daily_demand"
        connector = _bigquery(
            jobs={
                query: _Job(
                    schema=[("taxi_zone_id", "INT64"), ("centroid", "GEOGRAPHY")],
                    rows=[(1, "POINT(-73.98 40.75)"), (2, "POINT(-73.95 40.73)")],
                    total_bytes_processed=128,
                )
            }
        )
        destination = make_workspace() / "zones.parquet"
        rows = connector.materialize(query, destination, ConnectorLimits())
        self.assertEqual(rows, 2)
        duck = connect_spatial()
        try:
            path = destination.as_posix()
            described = dict(
                (str(name), str(type_name))
                for name, type_name, *_ in duck.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
            )
            # BigQuery GEOGRAPHY has exactly one CRS, and the column carries
            # it: OGC:CRS84 is GeoParquet's spelling of lon/lat WGS84.
            self.assertTrue(described["centroid"].startswith("GEOMETRY"), described["centroid"])
            self.assertIn("CRS84", described["centroid"])
            self.assertEqual(described["taxi_zone_id"], "BIGINT")
            read = duck.execute(
                f"SELECT taxi_zone_id, ST_X(centroid) FROM read_parquet('{path}') ORDER BY taxi_zone_id"
            ).fetchall()
        finally:
            duck.close()
        self.assertEqual(read[0][0], 1)
        self.assertAlmostEqual(read[0][1], -73.98, places=6)

    def test_bignumeric_keeps_its_exact_digits(self) -> None:
        from decimal import Decimal

        huge = Decimal("1" * 30 + "." + "2" * 20)
        query = "SELECT id, amount FROM northstar_analytics.trip_events"
        connector = _bigquery(
            jobs={query: _Job(schema=[("id", "STRING"), ("amount", "BIGNUMERIC")], rows=[("a", huge)], total_bytes_processed=8)}
        )
        destination = make_workspace() / "amounts.parquet"
        connector.materialize(query, destination, ConnectorLimits())
        duck = connect_spatial()
        try:
            value = duck.execute(f"SELECT amount FROM read_parquet('{destination.as_posix()}')").fetchone()[0]
        finally:
            duck.close()
        self.assertEqual(Decimal(value), huge)


# -- MotherDuck doubles --------------------------------------------------------


class _SessionProxy:
    """A local DuckDB standing in for a `md:` session.

    Session setup the connector owns (`LOAD motherduck`, `ATTACH 'md:...'`) is
    answered here; every other statement is executed for real against an
    in-memory catalog attached under the same alias, so the connector's own
    SQL is exercised rather than mocked.
    """

    def __init__(self, connection, *, read_only_attach: bool = True) -> None:
        self._connection = connection
        self._read_only_attach = read_only_attach
        self.statements: list[str] = []

    def execute(self, statement: str, parameters=None):
        self.statements.append(statement)
        text = statement.strip().lower()
        if text == "load motherduck":
            return self
        if text.startswith("attach 'md:"):
            if "read_only" in text and not self._read_only_attach:
                raise RuntimeError("this build cannot attach md: read-only")
            return self
        return self._connection.execute(statement, parameters) if parameters else self._connection.execute(statement)

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def interrupt(self):
        self._connection.interrupt()

    def close(self):
        pass


def _motherduck_session(*, read_only_attach: bool = True):
    connection = connect_spatial()
    connection.execute("ATTACH ':memory:' AS warehouse")
    connection.execute("CREATE SCHEMA warehouse.market")
    connection.execute(
        "CREATE TABLE warehouse.market.zone_market_scores AS "
        "SELECT * FROM (VALUES (1, 0.8), (2, 0.4), (3, 0.6)) AS t(taxi_zone_id, market_score)"
    )
    connection.execute(
        "CREATE TABLE warehouse.market.relevant_pois AS "
        "SELECT 1 AS taxi_zone_id, 'charging' AS category, ST_Point(-73.98, 40.75) AS geom"
    )
    proxy = _SessionProxy(connection, read_only_attach=read_only_attach)
    return proxy, connection


@unittest.skipUnless(DUCKDB_AVAILABLE, "DuckDB Spatial is not available")
class MotherDuckTests(unittest.TestCase):
    def _connector(self, **kwargs):
        proxy, connection = _motherduck_session(**kwargs)
        self.addCleanup(connection.close)
        return MotherDuckConnector("md-token-abc", database="northstar_market", connect=lambda token: proxy), proxy

    def test_discovery_lists_the_attached_database_read_only(self) -> None:
        connector, proxy = self._connector()
        discovery = connector.discover(ConnectorLimits())
        self.assertEqual(discovery.backend, "motherduck")
        self.assertTrue(discovery.read_only)
        self.assertEqual(discovery.identity, {"database": "northstar_market"})
        by_name = {table.name: table for table in discovery.tables}
        self.assertEqual(by_name["zone_market_scores"].row_estimate, 3)
        self.assertEqual(by_name["relevant_pois"].geometry_column, "geom")
        self.assertTrue(any("READ_ONLY" in statement for statement in proxy.statements))
        joined = " | ".join(discovery.notes)
        self.assertIn("network access", joined)
        self.assertIn("what this token may read", joined)

    def test_a_session_that_cannot_attach_read_only_says_so(self) -> None:
        connector, _ = self._connector(read_only_attach=False)
        discovery = connector.discover(ConnectorLimits())
        self.assertFalse(discovery.read_only)
        self.assertTrue(any("could not ATTACH the database READ_ONLY" in note for note in discovery.notes))

    def test_plan_and_materialise_round_trip_through_geoparquet(self) -> None:
        connector, _ = self._connector()
        query = "SELECT taxi_zone_id, market_score FROM market.zone_market_scores WHERE market_score > 0.5"
        plan = connector.plan(query, ConnectorLimits())
        self.assertEqual(plan.row_count, 2)
        self.assertEqual([column["name"] for column in plan.columns], ["taxi_zone_id", "market_score"])
        destination = make_workspace() / "market.parquet"
        self.assertEqual(connector.materialize(query, destination, ConnectorLimits()), 2)
        duck = connect_spatial()
        try:
            read = duck.execute(
                f"SELECT taxi_zone_id FROM read_parquet('{destination.as_posix()}') ORDER BY 1"
            ).fetchall()
        finally:
            duck.close()
        self.assertEqual([row[0] for row in read], [1, 3])

    def test_the_row_cap_bounds_what_is_written(self) -> None:
        connector, _ = self._connector()
        destination = make_workspace() / "capped.parquet"
        rows = connector.materialize(
            "SELECT taxi_zone_id FROM market.zone_market_scores", destination, ConnectorLimits(max_rows=2)
        )
        self.assertEqual(rows, 2)

    def test_a_failing_query_reports_the_failure_without_the_statement(self) -> None:
        connector, _ = self._connector()
        with self.assertRaises(ConnectorError) as caught:
            connector.plan("SELECT * FROM market.does_not_exist", ConnectorLimits())
        self.assertEqual(caught.exception.code, "query_failed")


class MotherDuckPolicyTests(unittest.TestCase):
    """These need no DuckDB: they are about the contract, not the engine."""

    def test_a_missing_database_is_a_manifest_error(self) -> None:
        connector = MotherDuckConnector("token", database=None, connect=lambda token: None)
        with self.assertRaises(ConnectorError) as caught:
            connector.discover(ConnectorLimits())
        self.assertEqual(caught.exception.code, "database_undeclared")

    def test_a_session_without_the_motherduck_extension_is_unavailable_not_broken(self) -> None:
        class _NoExtension:
            def execute(self, statement, parameters=None):
                raise RuntimeError("Extension 'motherduck' not found")

            def close(self):
                pass

        connector = MotherDuckConnector("token", database="northstar_market", connect=lambda token: _NoExtension())
        with self.assertRaises(ConnectorUnavailable) as caught:
            connector.discover(ConnectorLimits())
        self.assertEqual(caught.exception.code, "driver_unavailable")


class CloudBackendRoutingTests(unittest.TestCase):
    def test_both_backends_are_declared_and_built_from_the_warehouse_block(self) -> None:
        self.assertIn("bigquery", BACKENDS)
        self.assertIn("motherduck", BACKENDS)
        root = Path(".")
        bq = load_connector(
            "bigquery",
            "service=default",
            project_root=root,
            warehouse={"backend": "bigquery", "project": "northstar-demo", "dataset": "northstar_analytics", "location": "US"},
        )
        self.assertEqual(bq.identity_for_manifest(), {
            "backend": "bigquery",
            "project": "northstar-demo",
            "dataset": "northstar_analytics",
            "location": "US",
        })
        md = load_connector(
            "motherduck", "token", project_root=root, warehouse={"backend": "motherduck", "database": "northstar_market"}
        )
        self.assertEqual(md.identity_for_manifest(), {"backend": "motherduck", "database": "northstar_market"})

    def test_neither_connector_repeats_its_credential_in_an_error(self) -> None:
        secret = "md_token_hunter2"
        connector = MotherDuckConnector(secret, database=None)
        with self.assertRaises(ConnectorError) as caught:
            connector.discover(ConnectorLimits())
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(connector.identity_for_manifest()))
        bq = BigQueryConnector("/secrets/key-hunter2.json", project="p", dataset=None)
        self.assertNotIn("hunter2", repr(bq.identity_for_manifest()))


@unittest.skipUnless(LIVE_BIGQUERY_PROJECT and LIVE_BIGQUERY_DATASET, "no live BigQuery fixture configured")
class LiveBigQueryCanaryTests(unittest.TestCase):
    """Runs only where a real fixture exists; see .github/workflows/cloud-canary.yml.

    The canary's job is to catch what a fake client cannot: that the API
    surface this connector depends on -- dry-run byte estimates,
    `maximum_bytes_billed`, GEOGRAPHY-as-WKT -- still behaves as assumed.
    """

    def _connector(self):
        return BigQueryConnector(
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "service=default",
            project=LIVE_BIGQUERY_PROJECT,
            dataset=LIVE_BIGQUERY_DATASET,
        )

    def test_discovery_reaches_the_dataset_read_only(self) -> None:
        discovery = self._connector().discover(ConnectorLimits())
        self.assertTrue(discovery.read_only)
        self.assertTrue(discovery.tables, "the live fixture dataset is empty")

    def test_the_scan_guard_refuses_before_the_query_runs(self) -> None:
        query = f"SELECT * FROM `{LIVE_BIGQUERY_PROJECT}`.`{LIVE_BIGQUERY_DATASET}`.{LIVE_BIGQUERY_TABLE}"
        with self.assertRaises(ConnectorError) as caught:
            self._connector().plan(query, ConnectorLimits(max_scan_bytes=1))
        self.assertEqual(caught.exception.code, "scan_limit_exceeded")

    def test_a_small_query_plans_with_a_real_byte_estimate(self) -> None:
        query = f"SELECT * FROM `{LIVE_BIGQUERY_PROJECT}`.`{LIVE_BIGQUERY_DATASET}`.{LIVE_BIGQUERY_TABLE}"
        plan = self._connector().plan(query, ConnectorLimits())
        self.assertIsNotNone(plan.scan_bytes)
        self.assertGreater(plan.scan_bytes, 0)
        self.assertGreaterEqual(plan.row_count, 0)


@unittest.skipUnless(LIVE_MOTHERDUCK_TOKEN and LIVE_MOTHERDUCK_DATABASE, "no live MotherDuck fixture configured")
class LiveMotherDuckCanaryTests(unittest.TestCase):
    def _connector(self):
        return MotherDuckConnector(LIVE_MOTHERDUCK_TOKEN, database=LIVE_MOTHERDUCK_DATABASE)

    def test_discovery_reaches_the_database(self) -> None:
        discovery = self._connector().discover(ConnectorLimits())
        self.assertTrue(discovery.tables, "the live market database is empty")
        self.assertTrue(any(table.name == "zone_market_scores" for table in discovery.tables))

    def test_a_snapshot_materialises_from_the_live_database(self) -> None:
        destination = make_workspace() / "live-market.parquet"
        rows = self._connector().materialize(
            "SELECT taxi_zone_id, market_score FROM market.zone_market_scores", destination, ConnectorLimits()
        )
        self.assertEqual(rows, 60)
        self.assertTrue(destination.exists())


if __name__ == "__main__":
    unittest.main()
