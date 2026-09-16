---
name: geospatial-data-discovery
description: "Find and assess authoritative geospatial datasets or catalogs against known requirements: coverage, feature meaning, access, license, completeness, versions and reproducible pinning. Use for public sources, STAC/Portolan catalogs and read-only discovery of user data. Route joint source/compute/storage/delivery architecture to open-map-stack; do not turn a bounded lookup into a full analysis project."
metadata:
  version: "0.4.0"
---

# Geospatial data discovery

Find data that answers the user's question, and show what is known about its
fitness. Dataset names, convenient APIs and plausible-looking geometries are
not evidence that the features have the intended meaning.

## Discover and assess

1. Establish the area, time/version, feature semantics, necessary attributes,
   resolution, completeness and intended use. Ask only for consequential
   missing requirements; record assumptions that are safe to proceed with.
2. Read `references/data-sources.md` for public sources and STAC/Portolan
   catalogs. For the user's warehouse/database, read
   `references/user-data-sources.md`; use credentials by reference and
   read-only inspection. Snapshot materialization follows the existing
   authorization boundary.
3. Prefer the authoritative provider for the requested meaning. Verify fields
   and code lists: ownership, active status, eligibility and missing values
   must not be inferred from a generic category. Preserve unknowns as unknown.
4. Check coverage and completeness using provider counts, pagination, catalog
   structure, partitions and spatial/temporal filters as applicable. Distinguish
   a sample from a complete extract and a partial catalog from absent data.
5. Identify a reproducible version or immutable snapshot, access method,
   retrieval time and license/attribution requirements. A URL containing
   `latest` is not an immutable pin. Report unresolved license or retention
   constraints without inventing terms or promising a future rerun.

Return a concise source assessment: provider/dataset, authoritative link,
coverage/time, relevant fields and predicates, access/pin strategy, completeness
evidence and material limitations. Compare alternatives when they change the
answer; do not download an entire dataset just to establish its existence.

## Boundaries and resources

Use `references/formats-and-crs.md` when inspecting coordinate systems, formats
or spatial extents. A bounded discovery answer does not require `project.yaml`,
a canonical pipeline or presentation artifacts. If the user asks for the
actual multi-stage analysis, use an installed `open-map-stack` or
`reproducible-gis-project`, or explain the needed next step; do not label a
source assessment as a completed material analysis.

When source choice depends on unresolved compute placement, continental scale,
team concurrency or delivery architecture, keep those coupled decisions with
the generalist. Do not choose an engine merely because a dataset is easy to
query with it.

`references/installation.md`, `templates/` and `examples/tartu-development/`
are locally available when preparing a handoff. Do not load them for a simple
dataset lookup. No sibling skill or third-party installation is required.

For optional product expertise, read `references/companion-skills.md`.
Keep GIS correctness and the task boundaries above when using a companion.
