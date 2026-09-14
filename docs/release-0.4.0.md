# 0.4.0 release preparation

Status: implementation under epic [#31](https://github.com/jaakla/openmapstack-skills/issues/31);
**not released and not yet accepted by final live evaluation**.

The collection retains `open-map-stack` and adds `reproducible-gis-project`,
`geospatial-data-discovery` and `spatial-sql`. Each has a complete installed
payload. One version, 0.4.0, covers the collection, skill metadata, Claude plugin
and separately installed CLI. There is no new `open-gis` identity.

## Distribution and ownership

[ADR 0005](maintainers/decisions/0005-standalone-skill-distribution.md) records the
CLI/assets investigation and decision before implementation. Use a matching
version-pinned Python package (or matching wheel/commit before publication) and
local generated assets in every selected skill. The Python wheel contains the
CLI and schemas; agent installers deliver the skill payloads.

The generalist owns the existing domain modules, global defaults, decision
matrices, triage and anti-patterns. Its `references/project-workflow.md` and
`project-spec.md` remain the canonical reproducibility guidance. Specialists
receive selected generated reference copies listed in `collection.json`;
`scripts/sync_skill_assets.py --check` detects drift. Root `templates/` and
`examples/tartu-development/` remain canonical. Installed examples omit downloaded
sources and generated outputs and are not claims of a newly completed analysis.

For external consumers, [snapshot/arm migration](openmapbench-interop.md) is
additive: v1 retains historical meaning, v2 records complete selected payloads.
The project schema and check API remain v1. Native collection discovery uses
routing-smoke v2; legacy single-skill discovery retains routing-smoke v1.

## Executed packaging checks (2026-09-14)

Environment: skills CLI **1.5.26**, Node **24.19.0**, Python **3.12**, Claude Code
**2.1.270**. The isolated offline install run used local image
`sha256:09b981ebd0d253b35e05fbdcdb8d36f5ec7fdf527625ba86350e1f213b7202a6`, a
read-only mount of controlled install inputs, and no host homes or credentials.
Build used setuptools 84.0.0 and wheel 0.48.0.

- Built `openmapstack-0.4.0-py3-none-any.whl`; installed with `pip install --no-deps --force-reinstall WHEEL` in a disposable container with core dependencies already present. `openmapstack --version` returned 0.4.0. This checks the wheel, not offline dependency acquisition.
- Installed each physically isolated skill directory with `skills add PATH --skill NAME -a codex --copy -y`; inspected local links/resources and created v2 snapshots without siblings or repository content.
- For both project and global scope, installed the real `v0.3.0` root payload, then explicitly reinstalled from the new layout using `skills add NEW_CHECKOUT --skill '*' -a codex --copy -y` (plus `-g` for global). Four unique identities were present, with the existing `open-map-stack` replaced in place. No root shim was needed for this path.
- All four installed examples passed `openmapstack validate EXAMPLE/project.yaml --preflight` in both scopes: 26 passes, one existing license warning, no failures. Source downloads and full example reruns were outside this check.
- Listed and removed the collection in both scopes with `skills list` / `skills remove open-map-stack reproducible-gis-project geospatial-data-discovery spatial-sql -a codex -y` (plus `-g` globally). No installed skills remained.
- In a disposable local marketplace, `claude plugin marketplace add PATH`, `plugin install open-map-stack@open-map-stack`, then marketplace update and plugin update advanced the installed version from 0.3.0 to 0.4.0. Inventory showed all four skills. Plugin uninstall and marketplace removal left `plugin list --json` empty. No model or network call was needed.
- `claude plugin validate . --strict` passed; `claude --plugin-dir . plugin details open-map-stack` discovered exactly the four skills. These local plugin commands make no model call.

These observations cover actual installer execution and explicit replacement.
They do **not** establish hosted `skills update`, GitHub release pinning or
GitHub-backed marketplace refresh. The plugin lifecycle was tested using a
controlled local marketplace. Keep those checks separate below.

The historical repository slug `jaakla/open-gis` was verified through GitHub's
API to resolve to `jaakla/openmapstack-skills`. Public installation commands use
the canonical slug; redirect availability does not prove an existing lockfile
upgrades successfully.

## Deterministic evidence

The completed collection passed 503 unit tests (29 environment-dependent skips).
Fixture evals passed 16/16 contract cases and detected 26/26 controlled mutations;
two contract assertions were `not_testable` and two soft gates were unmet in this
runtime. Initial local assertion coverage was 68%, below the existing 70% gate,
with browser tests skipped because Playwright/Chromium were unavailable. CI's
browser-capable coverage gate remains required.

## Remaining release acceptance (#39)

- Execute automatic project/global update from a tracked 0.3.0 install against the final hosted layout, and pinned installs from the intended release revision. Record lockfile paths and source revisions before/after.
- Exercise old repository slugs and legacy `open-gis` coexistence in an isolated installation. Preserve the retained `open-map-stack`; explicitly remove an unwanted legacy identity. Never rewrite actual user lockfiles as part of testing.
- Verify the GitHub-backed marketplace refresh against the final hosted revision; the isolated local marketplace install/update/removal path already passes.
- Run and review the [small final-state acceptance set](../evals/final-state-acceptance.md), confirming trial count and available paid budget first. Do not require historical equivalence. Capture truthful native selection and task outcomes for all four skills, standalone fallback and optional companions.
- Finish required CI and relevant fixture checks on the final commit; run visual/QGIS evidence in the capable environment when needed for final material delivery. Resolve failures before release.
- After acceptance, build the coordinated release artifacts and publish only through the maintainer's release process. This implementation does not publish a tag or package.
