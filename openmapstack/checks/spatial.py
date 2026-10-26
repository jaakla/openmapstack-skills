"""Controlled DuckDB Spatial loading for deterministic evals.

Grading code never downloads extensions.  A preparation step may explicitly
install Spatial into a pinned directory, after which tests and evals only use
``LOAD spatial``.  This separation lets CI prove the suite inside a container
whose network is disabled at runtime.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

EXTENSION_DIR_ENV = "OPENMAPSTACK_SPATIAL_EXTENSION_DIR"


def configure_spatial_axes(connection: Any) -> None:
    """Use GIS x/y order after loading Spatial, including GDAL I/O."""
    connection.execute("SET geometry_always_xy = true")


def _connection_config() -> dict[str, str]:
    configured = os.environ.get(EXTENSION_DIR_ENV)
    if not configured:
        return {}
    extension_dir = Path(configured).expanduser().resolve()
    extension_dir.mkdir(parents=True, exist_ok=True)
    return {"extension_directory": str(extension_dir)}


def connect_spatial(*, install: bool = False, config: dict[str, Any] | None = None) -> Any | None:
    """Return a Spatial-enabled DuckDB connection, or ``None`` if unavailable.

    ``install=False`` is intentional and is used by every assertion and
    generated pipeline.  Only ``evals/prepare_spatial.py`` passes
    ``install=True`` while image/dependency preparation still has network.
    """
    try:
        import duckdb
    except ImportError:
        return None

    connection = duckdb.connect(config={**_connection_config(), **(config or {})})
    try:
        connection.execute("LOAD spatial")
    except Exception:
        if not install:
            connection.close()
            return None

        try:
            connection.execute("INSTALL spatial")
            connection.execute("LOAD spatial")
        except Exception:
            connection.close()
            return None

    try:
        configure_spatial_axes(connection)
    except Exception:
        connection.close()
        raise
    return connection


def require_spatial() -> Any:
    connection = connect_spatial()
    if connection is None:
        directory = os.environ.get(EXTENSION_DIR_ENV, "DuckDB's default extension directory")
        raise RuntimeError(
            "DuckDB Spatial is not preinstalled in "
            f"{directory}; run evals/prepare_spatial.py before disabling network access"
        )
    return connection
