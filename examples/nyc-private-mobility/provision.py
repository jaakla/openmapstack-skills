#!/usr/bin/env python3
"""Provision the Northstar Mobility private-database fixture.

Infrastructure and setup only — provisioning never becomes part of the
accepted analytical pipeline (`pipeline.py` is the single canonical
analysis implementation and runs exclusively from pinned local snapshots).

PostGIS (implemented in this skeleton stage):

    python provision.py postgis          # schema.sql -> seed.sql -> security.sql
    python provision.py verify           # sanity-check the security boundary
    python provision.py destroy          # drop everything this fixture created

BigQuery and MotherDuck provisioning arrive with their connectors (issue #43,
later steps): `provision.py all` will then cover all three backends.

Credentials:

    OMS_DEMO_POSTGIS_ADMIN_DSN            admin DSN used by provision/destroy
    OMS_DEMO_POSTGIS_READER_PASSWORD      password for the restricted reader
    OMS_DEMO_POSTGIS_DSN                  restricted reader DSN used by verify

The admin identity must never be used by the OpenMapStack project itself;
`project.yaml` references only `env:OMS_DEMO_POSTGIS_DSN`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SETUP = ROOT / "setup" / "postgis"

READER_NAME_DEFAULT = "oms_alpha_reader"


def _connect(dsn: str):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "provision.py requires psycopg: pip install 'openmapstack[postgis]'"
        ) from exc
    return psycopg.connect(dsn)


def substitute_variables(sql: str, params: dict[str, str]) -> str:
    """Substitute ``:name``, ``:'name'`` and ``:"name"`` like psql ``-v``.

    String literals, ``--`` comments, and ``::`` casts are left untouched;
    quoted forms quote the value safely and an unknown variable is an error,
    never a silent empty string.
    """
    spans: list[str] = []

    def mask(match: re.Match) -> str:
        spans.append(match.group(0))
        return f"\x00{len(spans) - 1}\x00"

    def quoted(match: re.Match) -> str:
        name = match.group(1) or match.group(2)
        quote = "'" if match.group(1) else '"'
        if name not in params:
            raise SystemExit(
                f"missing psql variable for placeholder :{name} (set it with -v or the environment)"
            )
        return quote + params[name].replace(quote, quote * 2) + quote

    # Quoted psql variables first (before string masking can swallow them),
    # then mask literals/comments and substitute bare :name placeholders.
    unquoted = re.sub(r":'([A-Za-z_]\w*)'|:\"([A-Za-z_]\w*)\"", quoted, sql)
    masked = re.sub(r"'(?:[^']|'')*'|--[^\n]*", mask, unquoted)

    def replacement(match: re.Match) -> str:
        name = match.group(1) or match.group(2) or match.group(3)
        quote = "'" if match.group(1) else '"' if match.group(2) else ""
        if name not in params:
            raise SystemExit(
                f"missing psql variable for placeholder :{name} (set it with -v or the environment)"
            )
        value = params[name].replace(quote, quote * 2)
        return f"{quote}{value}{quote}"

    substituted = re.sub(
        r"(?<!:):'(\w+)'|(?<!:):\"(\w+)\"|(?<!:):(\w+)",
        replacement,
        masked,
    )
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], substituted)


def _apply_sql_file(connection, path: Path, params: dict[str, str]) -> None:
    """Apply a SQL file with psql-compatible ``:var`` substitution."""
    sql = substitute_variables(path.read_text(encoding="utf-8"), params)
    with connection.cursor() as cursor:
        cursor.execute(sql)
    connection.commit()


# -- commands ------------------------------------------------------------------


def provision_postgis(admin_dsn: str, reader_name: str, reader_password: str) -> None:
    if not reader_password:
        raise SystemExit(
            "refusing to create the restricted reader without a password "
            "(--reader-password or OMS_DEMO_POSTGIS_READER_PASSWORD)"
        )
    params = {"reader_name": reader_name, "reader_password": reader_password}
    # Recreate the reader role deterministically. Grants and RLS policies
    # depend on the role, so they are cleared first (idempotent re-runs); the
    # tables themselves keep their deterministic data until seed.sql reruns.
    with _connect(admin_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE usename = %s AND pid <> pg_backend_pid()",
                (reader_name,),
            )
            for table, policy in (
                ("ops.hubs", "hubs_alpha_read"),
                ("ops.fleet_positions", "fleet_positions_alpha_read"),
                ("ops.service_areas", "service_areas_alpha_read"),
                ("ops.customer_accounts", "customer_accounts_alpha_read"),
            ):
                cursor.execute(f"SELECT to_regclass('{table}')")
                if cursor.fetchone()[0] is not None:
                    cursor.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
            for schema in ("ops", "hr"):
                cursor.execute("SELECT to_regnamespace(%s)", (schema,))
                if cursor.fetchone()[0] is not None:
                    cursor.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{reader_name}"')
                    cursor.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{reader_name}"')
            cursor.execute(f'DROP ROLE IF EXISTS "{reader_name}"')
        connection.commit()
        for name in ("schema.sql", "seed.sql", "security.sql"):
            print(f"applying {name}")
            _apply_sql_file(connection, SETUP / name, params)
    print("postgis fixture provisioned")


def verify_postgis(reader_dsn: str) -> int:
    """Sanity-check the security boundary through the restricted reader."""
    from openmapstack.connectors import ConnectorLimits
    from openmapstack.connectors.postgis import PostGISConnector

    connector = PostGISConnector(reader_dsn)
    discovery = connector.discover(ConnectorLimits(timeout_s=30.0))
    report = {
        "database": discovery.identity.get("database"),
        "read_only": discovery.read_only,
        "tables": [table.to_dict() for table in discovery.tables],
    }
    print(json.dumps(report, indent=2))

    connection = _connect(reader_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM ops.taxi_zones")
            zones = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM ops.fleet_positions")
            fleet = cursor.fetchone()[0]
            cursor.execute("SELECT count(DISTINCT tenant_id) FROM ops.hubs")
            hub_tenants = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM ops.customer_accounts WHERE tenant_id <> 'alpha'")
            other_tenant_rows = cursor.fetchone()[0]
            failures = []
            for denied, label in (
                ("SELECT * FROM ops.customer_accounts LIMIT 1", "SELECT * on customer_accounts"),
                ("SELECT contact_email FROM ops.customer_accounts LIMIT 1", "contact_email column"),
                ("SELECT count(*) FROM hr.driver_private", "hr.driver_private"),
            ):
                try:
                    cursor.execute(denied)
                    failures.append(label)
                except Exception:
                    connection.rollback()
    finally:
        connection.close()
    checks = {
        "taxi_zones >= 60": zones >= 60,
        "fleet_positions RLS-visible": fleet > 0,
        "hubs only tenant alpha": hub_tenants == 1,
        "no other-tenant rows visible": other_tenant_rows == 0,
        "protected columns and relations denied": not failures,
    }
    for label, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}: {label}")
    if failures:
        print(f"  unexpectedly readable: {failures}")
    if not all(checks.values()):
        print("verification FAILED")
        return 1
    print("verification passed")
    return 0


def destroy_postgis(admin_dsn: str, reader_name: str) -> None:
    with _connect(admin_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS ops CASCADE")
            cursor.execute("DROP SCHEMA IF EXISTS hr CASCADE")
            cursor.execute(f'DROP ROLE IF EXISTS "{reader_name}"')
        connection.commit()
    print("postgis fixture destroyed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["postgis", "all", "verify", "destroy"])
    parser.add_argument("--admin-dsn", default=None, help="defaults to OMS_DEMO_POSTGIS_ADMIN_DSN")
    parser.add_argument("--reader-dsn", default=None, help="defaults to OMS_DEMO_POSTGIS_DSN")
    parser.add_argument("--reader-name", default=READER_NAME_DEFAULT)
    parser.add_argument(
        "--reader-password",
        default=None,
        help="defaults to OMS_DEMO_POSTGIS_READER_PASSWORD; never committed or logged",
    )
    args = parser.parse_args(argv)

    admin_dsn = args.admin_dsn or os.environ.get("OMS_DEMO_POSTGIS_ADMIN_DSN", "")
    reader_dsn = args.reader_dsn or os.environ.get("OMS_DEMO_POSTGIS_DSN", "")
    reader_password = args.reader_password or os.environ.get("OMS_DEMO_POSTGIS_READER_PASSWORD", "")

    if args.command in ("postgis", "all"):
        if not admin_dsn:
            raise SystemExit("an admin DSN is required: --admin-dsn or OMS_DEMO_POSTGIS_ADMIN_DSN")
        provision_postgis(admin_dsn, args.reader_name, reader_password)
        return 0
    if args.command == "verify":
        if not reader_dsn:
            raise SystemExit("a reader DSN is required: --reader-dsn or OMS_DEMO_POSTGIS_DSN")
        return verify_postgis(reader_dsn)
    if args.command == "destroy":
        if not admin_dsn:
            raise SystemExit("an admin DSN is required: --admin-dsn or OMS_DEMO_POSTGIS_ADMIN_DSN")
        destroy_postgis(admin_dsn, args.reader_name)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
