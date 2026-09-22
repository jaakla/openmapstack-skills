"""BigQuery and MotherDuck fixture SQL (examples/nyc-private-mobility/setup/).

Two layers, for two different reasons.

The MotherDuck fixture is written as ordinary DuckDB SQL precisely so it can
be *executed* here: the same schema, seed and view definitions that
`provision.py motherduck` sends to `md:` run against a local in-memory
catalog, so a syntax error or a drifted row count fails on every PR with no
account and no network.

The BigQuery fixture cannot be executed without a billed project, so these
are contract assertions on the text: the security boundary must be declared,
the seed must be deterministic and idempotent, every psql variable must
resolve, and column-level security must stay a separate, explicitly requested
step rather than something a reader could mistake for applied. Live BigQuery
behaviour is the canary workflow's job (`.github/workflows/cloud-canary.yml`),
and a missing account there is reported as `not_testable`, never as a pass.
"""

from __future__ import annotations

import importlib.util
import io
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from openmapstack.checks.spatial import connect_spatial

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "nyc-private-mobility"
BIGQUERY = EXAMPLE / "setup" / "bigquery"
MOTHERDUCK = EXAMPLE / "setup" / "motherduck"
DUCKDB_AVAILABLE = connect_spatial() is not None

BIGQUERY_PARAMS = {
    "project": "northstar-demo",
    "dataset": "northstar_analytics",
    "restricted_dataset": "northstar_analytics_restricted",
    "location": "US",
    "reader_principal": "serviceAccount:oms-alpha-reader@northstar-demo.iam.gserviceaccount.com",
    "policy_tag": "projects/northstar-demo/locations/us/taxonomies/1/policyTags/2",
}
PROTECTED_COLUMNS = ("internal_cost", "rider_reference")
TENANT_TABLES = ("trip_events", "zone_daily_demand", "vehicle_daily_metrics")


def _load_provision():
    spec = importlib.util.spec_from_file_location("nyc_provision_cloud", EXAMPLE / "provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rendered(name: str) -> str:
    return _load_provision().substitute_variables((BIGQUERY / name).read_text(encoding="utf-8"), BIGQUERY_PARAMS)


def _code(sql: str) -> str:
    """Drop `--` comments: a comment may discuss what the SQL must not do."""
    return re.sub(r"--[^\n]*", " ", sql)


def _outside_literals(sql: str) -> str:
    """Drop comments *and* string literals, so a value like
    `serviceAccount:oms-...` is not mistaken for a `:placeholder`."""
    return re.sub(r"'(?:[^']|'')*'", "''", _code(sql))


@unittest.skipUnless(DUCKDB_AVAILABLE, "DuckDB Spatial is not available")
class MotherDuckFixtureExecutionTests(unittest.TestCase):
    """The `md:` fixture is DuckDB SQL, so it is run, not just read."""

    def _apply(self, *names: str):
        connection = connect_spatial()
        self.addCleanup(connection.close)
        connection.execute("ATTACH ':memory:' AS northstar_market")
        connection.execute("USE northstar_market")
        for name in names or ("schema.sql", "seed.sql", "security.sql"):
            connection.execute((MOTHERDUCK / name).read_text(encoding="utf-8"))
        return connection

    def test_the_fixture_applies_and_holds_its_declared_volumes(self) -> None:
        connection = self._apply()
        counts = {
            table: connection.execute(f"SELECT count(*) FROM market.{table}").fetchone()[0]
            for table in ("zone_market_scores", "relevant_pois", "analyst_annotations")
        }
        self.assertEqual(counts, {"zone_market_scores": 60, "relevant_pois": 240, "analyst_annotations": 24})
        low, high = connection.execute("SELECT min(taxi_zone_id), max(taxi_zone_id) FROM market.relevant_pois").fetchone()
        self.assertGreaterEqual(low, 101)
        self.assertLessEqual(high, 160)
        self.assertEqual(
            connection.execute("SELECT count(*) FROM market.relevant_pois WHERE geom IS NULL").fetchone()[0], 0
        )

    def test_the_seed_is_deterministic_and_idempotent(self) -> None:
        def digest(connection) -> tuple:
            return (
                connection.execute("SELECT round(sum(market_score), 6) FROM market.zone_market_scores").fetchone()[0],
                connection.execute("SELECT string_agg(poi_id, ',' ORDER BY poi_id) FROM market.relevant_pois").fetchone()[0],
                connection.execute(
                    "SELECT round(sum(confidence), 6) FROM market.analyst_annotations"
                ).fetchone()[0],
            )

        first = digest(self._apply())
        second_connection = self._apply()
        before_rerun = digest(second_connection)
        # Re-applying must land on the same rows, not double them.
        second_connection.execute((MOTHERDUCK / "seed.sql").read_text(encoding="utf-8"))
        self.assertEqual(first, before_rerun)
        self.assertEqual(digest(second_connection), first)
        self.assertEqual(
            second_connection.execute("SELECT count(*) FROM market.relevant_pois").fetchone()[0], 240
        )

    def test_the_analysis_views_exclude_the_private_annotations(self) -> None:
        connection = self._apply()
        views = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_catalog = 'northstar_market' AND table_type = 'VIEW'"
            ).fetchall()
        }
        self.assertIn("analysis_zone_scores", views)
        self.assertIn("analysis_zone_poi_counts", views)
        definitions = _code((MOTHERDUCK / "security.sql").read_text(encoding="utf-8"))
        self.assertNotIn("analyst_annotations", definitions, "no analysis view may republish the private notes")
        counted = connection.execute(
            "SELECT sum(total_pois) FROM market.analysis_zone_poi_counts"
        ).fetchone()[0]
        self.assertEqual(counted, 240)

    def test_the_seed_uses_a_checked_seed_not_a_random_source(self) -> None:
        body = _code((MOTHERDUCK / "seed.sql").read_text(encoding="utf-8"))
        self.assertIn("20260917", body)
        self.assertIn("md5_number(", body)
        for forbidden in ("random()", "now()", "current_timestamp", "current_date"):
            self.assertNotIn(forbidden, body.lower(), forbidden)
        self.assertIn("DELETE FROM", body)  # idempotent re-runs


class BigQueryFixtureContractTests(unittest.TestCase):
    """Executed only by the cloud canary; asserted as text on every PR."""

    def test_every_variable_resolves_in_every_file(self) -> None:
        for path in sorted(BIGQUERY.glob("*.sql")):
            with self.subTest(path=path.name):
                rendered = _load_provision().substitute_variables(
                    path.read_text(encoding="utf-8"), BIGQUERY_PARAMS
                )
                leftovers = re.findall(r"(?<!:):[A-Za-z_]\w*", _outside_literals(rendered))
                self.assertEqual(leftovers, [], f"unsubstituted placeholders in {path.name}")
                self.assertIn(BIGQUERY_PARAMS["dataset"], rendered)

    def test_the_protected_columns_exist_to_be_protected(self) -> None:
        schema = _rendered("schema.sql")
        for column in PROTECTED_COLUMNS:
            self.assertIn(column, schema, column)
        self.assertIn("GEOGRAPHY", schema)
        self.assertIn("PARTITION BY", schema)
        # The restricted dataset is a separate dataset, which is what makes it
        # grantable-to-nobody.
        self.assertIn(BIGQUERY_PARAMS["restricted_dataset"], schema)
        self.assertIn("driver_costs", schema)

    def test_the_reader_is_granted_the_analysis_dataset_and_revoked_the_restricted_one(self) -> None:
        security = _code(_rendered("security.sql"))
        granted = security.split("GRANT ", 1)[1].split(";", 1)[0]
        self.assertIn(BIGQUERY_PARAMS["dataset"], granted)
        self.assertNotIn(BIGQUERY_PARAMS["restricted_dataset"], granted)
        revoked = security.split("REVOKE ", 1)[1].split(";", 1)[0]
        self.assertIn(BIGQUERY_PARAMS["restricted_dataset"], revoked)
        self.assertIn(BIGQUERY_PARAMS["reader_principal"], security)

    def test_every_tenant_bearing_table_carries_a_row_access_policy(self) -> None:
        security = _code(_rendered("security.sql"))
        policies = re.findall(r"ROW ACCESS POLICY\s+(\w+)\s+ON\s+\S+\.(\w+)", security)
        self.assertEqual({table for _, table in policies}, set(TENANT_TABLES))
        self.assertEqual(security.count("FILTER USING (tenant_id = 'alpha')"), len(TENANT_TABLES))

    def test_column_security_stays_a_separate_explicitly_requested_step(self) -> None:
        """A fixture that implied column security it had not applied would be
        worse than one that applies none: the security.sql text must not
        claim it, and the ALTERs must live in their own file."""
        security = _code(_rendered("security.sql"))
        self.assertNotIn("policy_tags", security)
        column_security = _rendered("column-security.sql")
        for column in PROTECTED_COLUMNS:
            self.assertIn(f"ALTER COLUMN {column}", column_security, column)
        self.assertIn(BIGQUERY_PARAMS["policy_tag"], column_security)

    def test_the_seed_is_deterministic_and_idempotent(self) -> None:
        body = _code(_rendered("seed.sql"))
        self.assertIn("20260917", body)
        self.assertIn("FARM_FINGERPRINT", body)
        for forbidden in ("RAND()", "CURRENT_TIMESTAMP()", "CURRENT_DATE()", "GENERATE_UUID()"):
            self.assertNotIn(forbidden, body, forbidden)
        self.assertEqual(body.count("TRUNCATE TABLE"), 4)

    def test_no_real_operator_is_implied_by_the_fixture(self) -> None:
        for path in sorted(BIGQUERY.glob("*.sql")):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("bigquery-public-data", _code(text))


class FixtureManifestTests(unittest.TestCase):
    """`fixture.yaml` describes the boundary; the SQL creates it. Drift between
    the two would make the documented access matrix quietly wrong, which is
    the one thing a security fixture may not be."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = yaml.safe_load((EXAMPLE / "fixture.yaml").read_text(encoding="utf-8"))

    def test_every_declared_relation_exists_in_the_setup_sql(self) -> None:
        sql = {
            "postgis": (EXAMPLE / "setup" / "postgis" / "schema.sql").read_text(encoding="utf-8"),
            "bigquery": (BIGQUERY / "schema.sql").read_text(encoding="utf-8"),
            "motherduck": (MOTHERDUCK / "schema.sql").read_text(encoding="utf-8"),
        }
        for backend, text in sql.items():
            for relation in self.fixture["backends"][backend]["relations"]:
                bare = relation["name"].rsplit(".", 1)[-1]
                with self.subTest(backend=backend, relation=relation["name"]):
                    self.assertIn(bare, text)

    def test_no_restriction_claims_an_enforcer_it_does_not_have(self) -> None:
        """A restriction whose enforcement is a convention must say so, and a
        restriction that is optional must name what applies it."""
        for backend, block in self.fixture["backends"].items():
            for restriction in block["restrictions"]:
                with self.subTest(backend=backend, kind=restriction["kind"]):
                    self.assertIn("enforced_by", restriction)
                    if restriction["kind"] == "convention":
                        self.assertIn("nothing", restriction["enforced_by"])
        column_level = next(
            item for item in self.fixture["backends"]["bigquery"]["restrictions"] if item["kind"] == "column_level"
        )
        self.assertIn("applied_when", column_level, "an optional restriction must name how it is applied")
        self.assertIn("--policy-tag", column_level["applied_when"])

    def test_the_analysis_identity_is_declared_by_reference_only(self) -> None:
        identities = self.fixture["identities"]
        self.assertNotEqual(identities["provisioning"]["credentials"], identities["analysis"]["credentials"])
        project = yaml.safe_load((EXAMPLE / "project.yaml").read_text(encoding="utf-8"))
        referenced = {
            source["access"]["connection"]["ref"].split(":", 1)[1] for source in project["sources"].values()
        }
        self.assertTrue(referenced.issubset(set(identities["analysis"]["credentials"])), referenced)
        self.assertFalse(referenced & set(identities["provisioning"]["credentials"]))

    def test_verification_distinguishes_not_configured_from_passed(self) -> None:
        reports = self.fixture["verification"]["reports"]
        self.assertEqual(set(reports), {"pass", "fail", "not_configured"})
        self.assertIn("not a pass", reports["not_configured"])


class ProvisionCommandTests(unittest.TestCase):
    """`all` and `verify` must report an unconfigured backend, never pass it."""

    def _run(self, argv, environment):
        import os

        provision = _load_provision()
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(environment)
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                code = provision.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        return code, out.getvalue()

    def test_all_with_no_credentials_provisions_nothing_and_says_so(self) -> None:
        code, output = self._run(["all"], {})
        self.assertEqual(code, 1)
        self.assertIn("provisioned: nothing", output)
        self.assertIn("SKIPPED (no credentials configured): postgis, bigquery, motherduck", output)

    def test_verify_with_no_credentials_fails_rather_than_reporting_success(self) -> None:
        code, output = self._run(["verify"], {})
        self.assertEqual(code, 1)
        self.assertIn("NOT VERIFIED (no reader credentials configured)", output)
        self.assertNotIn("verification passed", output)

    def test_destroy_skips_what_it_has_no_admin_credential_for(self) -> None:
        code, output = self._run(["destroy"], {})
        self.assertEqual(code, 0)
        self.assertIn("destroyed: nothing", output)
        self.assertIn("SKIPPED (no admin credentials configured)", output)

    def test_bigquery_provisioning_refuses_without_the_reader_principal(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self._run(["bigquery", "--bigquery-project", "northstar-demo"], {})
        self.assertIn("reader-principal", str(caught.exception))

    def test_the_report_helper_separates_failures_from_unconfigured_checks(self) -> None:
        provision = _load_provision()
        out = io.StringIO()
        with redirect_stdout(out):
            ok = provision.report("bigquery", {"a": True, "b": False}, ["column-level security"])
        self.assertFalse(ok)
        self.assertIn("FAIL: b", out.getvalue())
        self.assertIn("NOT CONFIGURED: column-level security", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            ok = provision.report("motherduck", {"a": True}, ["READ_ONLY attach"])
        self.assertTrue(ok, "an unconfigured check is not a failure, but it is not a pass either")
        self.assertIn("NOT CONFIGURED", out.getvalue())


if __name__ == "__main__":
    unittest.main()
