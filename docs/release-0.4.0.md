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

## Executed hosted update and pin checks (2026-09-16)

Environment: skills CLI **1.5.26**, Node **24.19.0**, `openmapstack` from the
checkout virtualenv. Each scenario used a fresh throwaway `HOME` (no `XDG_*`,
no credentials, `DO_NOT_TRACK=1`), cloning the hosted `jaakla/openmapstack-skills`.
Intended release revision: `main` at `534792f438a4d263e3ef4105e7a53b63baa330d5`
(merge of PR #41; tree identical to `c269df4`). There is no `v0.4.0` tag yet,
so pinning used that commit in place of the tag.

Lockfile paths: project `<project>/skills-lock.json`; global
`$HOME/.agents/.skill-lock.json`.

**Tracked 0.3.0 → `skills update`.** Installed `jaakla/openmapstack-skills#v0.3.0 --skill open-map-stack -a codex --copy`.
The CLI records `ref: v0.3.0`. A floating install made while `main` was at
`v0.3.0` would record the same entry without `ref` (`v0.3.0` is an ancestor of
`main`). To reproduce that tracked state, the disposable lock had only its `ref`
field removed. Then `skills update open-map-stack --project|--global -y` ran.

| Scope | Lock field | Before | After |
|---|---|---|---|
| project | `skillPath` | `SKILL.md` | `skills/open-map-stack/SKILL.md` |
| project | `computedHash` | `2ad62396…c9fdf3a` | `ba968b12…c06667a` |
| global | `skillPath` | `SKILL.md` | `skills/open-map-stack/SKILL.md` |
| global | `skillFolderHash` | `d4e1bd3c…` (`v0.3.0` commit) | `f3eda402…` (= `534792f:skills/open-map-stack`) |

- Both updates exited 0. Global update reported "Skill paths changed; resolving via Git clone"; no manual migration or root shim was needed.
- The payload went from the 213-file 0.3.0 root copy (no `metadata.version`) to the 27-file 0.4.0 skill directory. It is byte-identical to `skills/open-map-stack/` with no stale 0.3.0 files. The identity `open-map-stack` was kept.
- A second global update reported "All global skills are up to date". Project update re-adds on every run without changing the lock.
- Update only refreshes tracked identities. The three new specialists are **not** added automatically; users must `skills add` them explicitly.
- Update re-runs `add` without the original `-a codex`, so agent targets come from auto-detection. In the empty `HOME` this created links for 55 other agent directories (global) and `.claude/skills` plus `agent/skills` (project). Real homes may differ.

**Control: pinned `v0.3.0` (ref retained).** `skills update` in both scopes
left the lock (`ref: v0.3.0`, `skillPath: SKILL.md`, same hash) and payload
unchanged.

**Pinned release revision.** Installed each skill with
`skills add https://github.com/jaakla/openmapstack-skills/tree/534792f…/skills/NAME -a codex --copy -y`
(plus `-g`). Each entry recorded `ref: 534792f…` and its `skills/NAME/SKILL.md`.
Global `skillFolderHash` values equal the release trees: `open-map-stack f3eda402`,
`reproducible-gis-project 2036c375`, `geospatial-data-discovery c0eab20c`, `spatial-sql ce84dd29`.
All four report `metadata.version` 0.4.0. `openmapstack validate EXAMPLE/project.yaml --preflight`
gave 26 passes, one existing license warning and no failures for all four examples in both scopes.
A following `skills update` kept locks and payload hashes identical in both scopes.

Not covered: pinning to the eventual `v0.4.0` tag (does not exist yet).

## Executed old-slug, legacy identity and marketplace checks (2026-09-16)

Same isolation and tooling as above. Both historical slugs, `jaakla/open-gis`
(before rename `4ebe23f`) and `jaakla/openmapstack` (0.2.0/0.3.0 README), resolve
to `jaakla/openmapstack-skills`. Tracked floating entries were reproduced by removing `ref`
from disposable locks only. Results were identical in project and global scope.

- **Legacy `open-gis`.** Tracked from `jaakla/open-gis` at `8ac8554`; lock `skillPath: SKILL.md`.
  - `skills update -y` warned that `open-gis` "appear[s] to have been deleted upstream" and skipped deletion in non-interactive mode. The lock and 115-file payload stayed unchanged; exit was 0.
  - `skills add jaakla/openmapstack-skills --skill '*' -a codex --copy -y` added all four 0.4.0 identities beside it. They coexist as separate entries; nothing is migrated.
  - `skills remove open-gis -a codex -y` removed only the legacy entry and folder. The four canonical entries kept their `skillPath` and hashes, and all four examples passed preflight (26 passes, one license warning).
- **Old slug `jaakla/openmapstack`, tracked 0.3.0 → update.** Same result as the canonical slug: `skillPath SKILL.md → skills/open-map-stack/SKILL.md`, global hash `d4e1bd3 → f3eda40`. The lock `source` keeps the old slug.
- **Completing the set.** After the update above, `skills add jaakla/openmapstack-skills --skill '*'` replaced the `open-map-stack` entry in place. It set `source` to the canonical slug and added the three specialists; a following update kept all four. A tracked 0.3.0 from `jaakla/open-gis` reached the same four-skill state directly with that `add`, without a prior update.
- **Automatic update installs only tracked identities.** Specialists are added only by the explicit `add`. The generalist remains a superset of 0.3.0 references and of every specialist's shared references, with standalone fallback.
- **GitHub-backed Claude Code marketplace (Claude Code 2.1.273).**
  - Isolated `CLAUDE_CONFIG_DIR`: `claude plugin marketplace add 'jaakla/openmapstack#v0.3.0'` and `plugin install open-map-stack@open-map-stack` installed 0.3.0 (`gitCommitSha d4e1bd3`).
  - After removing `ref` from the disposable `settings.json` / `known_marketplaces.json`, `plugin marketplace update open-map-stack` moved the marketplace checkout to `534792f`. `plugin update open-map-stack@open-map-stack -y` reported "updated from 0.3.0 to 0.4.0", recorded `gitCommitSha 534792f`, and `plugin details` listed all four skills. Cached `skills/` matched the repository.
  - Uninstall plus marketplace removal left `plugin list --json` empty and no configured marketplaces.
  - A fresh `marketplace add jaakla/openmapstack-skills` installed 0.4.0 (`534792f`, four skills). A subsequent update reported "already at the latest version", and removal left the inventory empty.
  - Plugin users therefore receive the full collection hands-off.

## Deterministic evidence

The completed collection passed 503 unit tests (29 environment-dependent skips).
Fixture evals passed 16/16 contract cases and detected 26/26 controlled mutations;
two contract assertions were `not_testable` and two soft gates were unmet in this
runtime. After preparing Playwright 1.62.0 and Chromium 151.0.7922.34, all 56 visual
assertion unit tests passed, including the 20 browser cases skipped in the
initial run. Combined assertion coverage reached **77%**, passing the existing
70% gate. PyQGIS, external PostGIS and optional live-catalog tests still need
their separate capable environments.

## Remaining release acceptance (#39)

- ~~Execute automatic project/global update from a tracked 0.3.0 install against the final hosted layout, and pinned installs from the intended release revision.~~ Done against `main@534792f`; see "Executed hosted update and pin checks". After tagging, repeat the pinned install with `tree/v0.4.0/...` if the tag's revision differs from `534792f`.
- ~~Exercise old repository slugs and legacy `open-gis` coexistence in an isolated installation.~~ Done; see "Executed old-slug, legacy identity and marketplace checks".
- ~~Verify the GitHub-backed marketplace refresh against the final hosted revision.~~ Done against `534792f`, same section.
- **Live routing acceptance (2026-09-16).**
  - Setup: `claude-sonnet-4-6`, Claude Code 2.1.270, image `sha256:e3e0c444…`, one trial per case. Authorized scope was the routing set only. Total reported spend: $3.72 of a $5 cap.
  - Payload: rounds 1–2 used the payload identical to `534792f`; the reruns and round 3 used the working tree with the guidance fixes below. Snapshot metadata records `c269df4` with `dirty: true`.
  - Some trials were rejected by the Claude subscription's five-hour window, and org overage was disabled (`org_level_disabled_until`). Those trials cost $0; the affected cases were rerun after the reset.

  | Case | Installed | Selection | Task outcome | Cost |
  |---|---|---|---|---|
  | `bounded-discovery` | collection | passed (`geospatial-data-discovery`) | **failed**: recommended `resultType=hits` completeness | $0.26 |
  | `chosen-engine-sql` | collection | passed (`spatial-sql`) | **failed**: claimed a `geom` GiST index serves `::geography` casts | $0.12 |
  | `casual-place-lookup` | collection | passed (no GIS skill) | passed | $0.02 |
  | `bounded-discovery` | discovery only | passed | failed (same hits advice; before fix) | $0.13 |
  | `chosen-engine-sql` | spatial-sql only | passed | failed (same index claim; before fix) | $0.12 |
  | `chosen-engine-sql` (after fix) | spatial-sql only | passed | **passed**: expression index, projected alternative, `Index Cond` vs `Join Filter` check | $0.24 |
  | `bounded-discovery` (after fix) | discovery only | passed | **passed**: paged `numberMatched`, `sortBy`, warns against capped hits. Minor: calls Overture buildings CDLA-Permissive (the theme is ODbL) | $0.25 |
  | `material-analysis-generalist-only` | generalist only | passed | passed: full project contract (immutable sources, asserted overrides, metric CRS, completeness, validation, provenance); unexecuted plan | $0.36 |
  | `ambiguous-architecture` | collection | passed (`open-map-stack`) | passed: gating questions and coupled compute/storage/delivery | $0.13 |
  | `billion-row-architecture` | collection | passed (`open-map-stack`) | passed: pinning/mirroring, partitioned GeoParquet, compute placement, cost, PMTiles/CDN. Minor: unverified rationale for Overture release retention | $0.36 |
  | `compile-existing-analysis` | collection | not_testable: read `reproducible-gis-project`, budget exhausted | not_testable | $0.71 |
  | `compile-existing-analysis` | reproducible-gis-project only | not_testable: read skill, $1.00 cap exhausted after 11 turns | not_testable | $1.03 |

  - **Guidance fixes.** Both task failures traced to shipped guidance or its gaps. The generalist references were corrected and synced to the specialists; after the fix, both reruns passed their task outcome.
    - `spatial-sql.md`: an index serves only its own expression; added geography-expression and `ST_Transform` expression index options. On PostGIS 3.4.3 with 500k synthetic parcels, a plain `geom` GiST index plus the `::geography` predicate gave a nested-loop scan in 12.5 s. `GIST ((geom::geography))` gave an index scan in 9 ms with the same 235 rows, and `GIST (ST_Transform(geom, 3301))` gave an index scan in 3.9 ms.
    - `validation-and-ops.md`: completeness comes from the paged response total, not a separate hits request.
    - `data-sources.md`: ETAK paging uses stable `sortBy` plus accumulated count equal to `numberMatched`. The live server returned `numberMatched="5000"` for hits but 22308 when paged (Tartu bbox).
    - Unit suite passed (9 skips); fixture evals 16/16 contract and 26/26 mutations.
  - **Regression guard for both corrections.** These two fixes are shipped prose,
    and the layers that would normally protect them do not reach it: the routing
    eval reports `task_success` as `not_testable` by construction
    (`evals/routing.py`), and the fixture evals grade produced projects rather
    than the reference text. `tests/test_guidance_regressions.py` therefore
    asserts that each corrected statement is still present in every shipped copy
    and that the retracted advice has not returned. Reverting either sentence
    fails the unit suite. This is a content guard only: it proves the guidance
    ships, not that an agent acts on it, which remains the job of the live
    `chosen-engine-sql` and `bounded-discovery` cases.
  - **Open.**
    - `compile-existing-analysis` has no complete live run: both attempts selected the right skill and then exceeded their caps ($0.50, $1.00). It needs a larger per-trial budget, or an investigation of why scaffold compilation is this expensive (e.g. reading the 60 KB `project-spec.md`).
    - Not in the authorized scope: executed `001` configurations and the four companion contexts.
    - The three bounded cases were not rerun with the full collection after the fix.
    - Task outcomes above are reviewer judgements against the
      `final-state-acceptance.md` rubric, not machine-graded scores. No automated
      layer grades analytical outcomes today.
- Run and review the [small final-state acceptance set](../evals/final-state-acceptance.md), confirming trial count and available paid budget first. Do not require historical equivalence. Capture truthful native selection and task outcomes for all four skills, standalone fallback and optional companions.
- Finish required CI and relevant fixture checks on the final commit; run visual/QGIS evidence in the capable environment when needed for final material delivery. Resolve failures before release. Status on `534792f`: push workflows `OpenMapStack fixture evals` (run 35089132445) and `Claude Code plugin manifests` (run 35089132462) passed; `example.yml` passed on identical tree `c269df4`. Visual workflow dispatched on `534792f` passed (run 35092610173): integration_visual 2/2, mutation_tests 2/2.
- After acceptance, build the coordinated release artifacts and publish only through the maintainer's release process. This implementation does not publish a tag or package.
