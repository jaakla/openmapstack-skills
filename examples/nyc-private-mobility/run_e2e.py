#!/usr/bin/env python3
"""Convenience entrypoint for the canonical Northstar Mobility pipeline.

All processing, validation, run metadata, and dashboard rendering live in
pipeline.py so the plain and E2E commands cannot drift. The pipeline runs
exclusively from pinned local snapshots — provisioning and snapshotting
(provision.py + `openmapstack source snapshot`) happen once, separately.
"""

from pipeline import main


if __name__ == "__main__":
    main()
