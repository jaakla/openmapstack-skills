# Tartu and NYC Observable delivery samples

Two real [Observable Framework](https://observablehq.github.io/framework/) apps
explore the existing city examples. They select `kind: observable`, export static
module bundles, and include input-bound delivery and integration evidence.
No Observable account or warehouse credentials are needed.

- **Tartu:** parcel tiers, road context, education points, area and distance table.
- **NYC:** H3 cells, borough and eligibility filters, fixed scores, synthetic fleet and existing hubs.

Both include reactive filters, hover details, reset, complete GeoJSON/CSV
downloads, and visible source provenance and limitations. They are report views
with thematic maps, without a street basemap.

## Build either sample

From the repository root, with Python 3.10+, Node 20+ and npm:

```bash
python3 -m pip install -e .
python3 examples/observable-cities/create.py /tmp/tartu-observable --city tartu
python3 /tmp/tartu-observable/pipeline.py
openmapstack validate /tmp/tartu-observable/project.yaml --preflight
openmapstack validate /tmp/tartu-observable/project.yaml
python3 -m http.server 8080 --bind 127.0.0.1 --directory /tmp/tartu-observable/views/observable
```

Open <http://127.0.0.1:8080/>. For NYC, choose `--city nyc` and a separate empty
destination. Module apps must be served over HTTP. `pipeline.py` installs the
locked Framework dependencies in a disposable build workspace and builds the
bundle; first builds need network access to fetch npm dependencies. The exported
app serves its modules and data locally, including when hosted below a Pages
subpath. Build logs are in `work/observable-build.log`.

The generated `project.yaml` declares a local Observable target, analytical
inputs, an authoritative Observable definition, a bundle inventory, and run
records. `openmapstack verify` can also exercise delivery evidence and runtime
health when its optional dependencies are installed. Clean reruns use the two
pinned source snapshots and declared implementation files.

## Snapshot scope

`create.py` copies and hashes the upstream `dashboard.html` and `project.yaml`.
The pipeline checks those pins, verifies their run IDs agree, and re-exports the
embedded public presentation data without executing dashboard JavaScript. This
also works in a fresh checkout: Tartu's larger derived files are intentionally
excluded from Git, while its dashboard contains the necessary snapshot.

This is a **delivery replay**, not a second execution of the original GIS
analysis. Original calculations, source captures, validation and scenario
definitions remain owned by [Tartu](../tartu-development/) and
[NYC](../nyc-private-mobility/). Filtering marks an exploratory subset and leaves
recorded scores, distances, tiers and accepted scenarios unchanged. The original
standalone HTML dashboards provide richer spatial/scenario editing controls.

The Tartu warnings about hypothetical overrides and unresolved municipal
education reuse terms, and NYC's synthetic-business/historical-TLC caveats,
remain visible. The original source manifest is pinned, and upstream source
providers, versions, licenses, capture metadata and assumptions appear in each
app's provenance section. The sample does not change those reuse terms.

## GitHub Pages

The project homepage links both formats beside each city:

- [Tartu Observable](https://jaakla.github.io/openmapstack-skills/demos/tartu-observable/)
- [NYC Observable](https://jaakla.github.io/openmapstack-skills/demos/nyc-observable/)

`python3 scripts/build_project_pages.py --output _site` builds both apps and
assembles the homepage, standalone dashboards and Observable bundles. The Pages
workflow performs that build on relevant pushes to `main` or manual dispatch.
The local delivery target remains `mode: local`: Pages hosts its exported bundle;
this does not claim deployment to Observable's hosted service.

## Maintainer checks

```bash
python3 -m unittest -v tests.test_observable_cities tests.test_project_pages
# After building both projects under /tmp/city-samples/{tartu,nyc}, with Playwright/Chromium installed:
OMS_OBSERVABLE_CITY_PROJECTS=/tmp/city-samples \
  python3 -m unittest -v tests.test_observable_cities.ObservableCityBrowserTests
```

The opt-in browser check validates both manifests and receipts, serves the apps
under a Pages-style subpath, exercises filters/reset, compares CSV download
bytes, checks errors and mobile overflow, and saves screenshots outside the repo
under `/tmp/oms-{city}-{desktop,mobile}.png`.
