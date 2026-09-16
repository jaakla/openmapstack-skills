# CLI and local project resources

This skill includes `templates/`, `schemas/project-v1.schema.json` and
`examples/tartu-development/`. Paths are relative to the installed skill root;
no other skill or repository checkout is required to read them. Copy templates
or the example into the user's project before modifying or executing them.

Use the OpenMapStack CLI matching this skill's `metadata.version` (0.4.0).
After 0.4.0 is published, install it in the project's Python environment:

```bash
python -m pip install 'openmapstack[geo]==0.4.0'
openmapstack --version
```

Until publication, install a wheel built from the same repository revision,
or install from a pinned Git commit supplied by the maintainer:

```bash
python -m pip install 'openmapstack[geo] @ git+https://github.com/jaakla/openmapstack-skills.git@<full-commit-sha>'
```

Do not substitute a floating branch or silently use a mismatched CLI. For
offline environments, prepare the pinned wheel and its dependency wheels
beforehand. The `geo` extra enables DuckDB checks; GDAL/QGIS/browser dependencies
remain environment-specific. Missing runtime checks are `not_testable`.

The trimmed Tartu example includes its canonical pipeline, manifest and scenario
geometry. Generated maps, source downloads and run outputs are omitted. Its
pipeline downloads real authoritative data and needs the GIS environment
documented in the example README; it is not an offline fixture. Existing
methodological and license warnings remain limitations, not successful checks.
Inspect `PACKAGE-NOTES.md` in the example before running it.
