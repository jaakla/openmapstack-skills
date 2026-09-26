# 0.4.0 final preparation review

Reviewed 2026-09-26 at `612e3963019f7bf35e006daea179d9d799709899`.
**Accepted for publication by the maintainer on 2026-09-26, with explicit exceptions #67 and #69.**
The maintainer closed live-trial gates and deferred #67. The maintainer also explicitly deferred
the occasional plain-versus-skill comparison until after 0.4.0. No paid calls were made in this
preparation round. After reviewing the new dashboard evidence, the maintainer explicitly deferred
those gaps to [#69](https://github.com/jaakla/openmapstack-skills/issues/69) and authorized 0.4.0
publication. These decisions do not change historical failures into passes.

[Machine-readable evidence](acceptance-0.4.0-final.json) records build/snapshot hashes, CI URLs,
local evidence hashes and limitations. [Earlier candidate evidence](acceptance-0.4.0-rc.json)
remains unchanged. The chronological [acceptance record](../evals/final-state-acceptance.md)
owns the live-trial history.

## Candidate and distribution

The full collection hash is
`sha256:2177d75e666914b4d4d87dba15c0741da1576d7e7509b8ebebcd5878b4d6e3a0`, identical to the
latest material trial at `9ef5c45`. Between that revision and `612e396`, only the acceptance
document changed. Full and four standalone v2 snapshots were created from the clean checkout
and independently reverified. This permits evidence carry-forward for unchanged payload bytes;
it does not claim every skill or task has a successful executed trial.

A wheel and sdist were built from a clean `git archive` of `612e396`; both passed `twine check`.
The installed wheel reports 0.4.0. These are prepublication artifacts: the GitHub release workflow
rebuilds its own distributions. Record the published hashes after that workflow finishes rather
than claiming its bytes match this local build.

Fresh hosted installs at the exact revision passed with skills CLI 1.5.26 and Node 24.19.0:

- Project and global scope, all four skill identities, copied into fresh isolated homes.
- Every installed file matched the corresponding repository payload byte-for-byte.
- All eight installed example preflights: 26 passes, one existing unresolved-license warning,
  zero failures each.
- A following pinned update preserved lockfile and payload bytes; removal left none of the four
  skills installed.

Claude Code 2.1.283 passed strict manifest validation and reported exactly four skills. A fresh
HTTPS-backed marketplace install from `main` recorded commit `612e396`, version 0.4.0 and the
four skills. Uninstall and marketplace removal left an empty plugin list. In this credential-free
environment, owner/repository shorthand chose SSH and failed; use HTTPS. A hexadecimal `#commit`
was treated as a remote branch by this CLI and failed; the successful `#main` install's recorded
commit was checked explicitly. These observations do not establish eventual tag pinning.

## Deterministic and visual checks

- [Fixture CI](https://github.com/jaakla/openmapstack-skills/actions/runs/36256525056): 667 unit
  tests, 28 skips, 78% assertion coverage against a 70% gate. Offline suite: 665 tests, 49 skips.
  Contract fixtures 16/16 and mutations 26/26; two unavailable assertions and two unmet soft gates
  remain visible.
- [Plugin CI](https://github.com/jaakla/openmapstack-skills/actions/runs/36256525080): passed.
- [Worked example](https://github.com/jaakla/openmapstack-skills/actions/runs/36268094610): fresh
  real-source regeneration, validation, verification, real-QGIS layer rendering and committed
  project currency all passed on `612e396`.
- [Visual integration](https://github.com/jaakla/openmapstack-skills/actions/runs/36268093376):
  QGIS/browser fixture integration 2/2 and visual mutations 2/2; zero unavailable assertions or
  unmet soft gates. This tests generated fixtures, not a live agent's dashboard.
- Local focused collection/version/snapshot/check-API/routing/guidance checks: 65 tests passed;
  generated skill asset sync passed. The existing `.venv` lacked PyYAML, so the successful focused
  run used system Python. Packaging/browser dependencies were installed in a disposable venv.

## Compilation review

The `compile-existing-analysis` prompt at `b65a2b4` explicitly requests a **manifest and pipeline
scaffold**, with unavailable source details identified. It does not supply the underlying files.
The retained response preserves the 500 m buffer/intersection algorithm in EPSG:3301, lists missing
source fields and pins rather than inventing them, and states that the CLI and pipeline were not
executed. It reports the absent QGIS artifact honestly.

Review disposition: useful bounded scaffold with limitations, not an accepted executed material
project. Extra export formats broaden the requested output, and `openmapstack==0.4.0` was not yet
published when the installation command was supplied. Native selection remains subject to the
recorded Bash telemetry gap; do not convert `not_testable` into `passed`. Execution correctness
cannot be inferred from this review. The earlier blanket “unexecuted scaffold cannot count” needs
this task-specific distinction: a scaffold can satisfy a scaffold request while proving no rerun.

## Companion review

This is an agent-assisted **static contract review**, not four live composition trials. The
control was generated by the committed reference pipeline and passed all 36 validation checks.
The bounded task is to expose its existing candidate output in a MapLibre map without changing
source bytes, selection, metric calculations, provenance or the canonical pipeline.

The external reference is MapLibre's `maplibre-tile-sources` at
[`8974bdf57503d296c5bd015a406ae32a698cc605`](https://github.com/maplibre/maplibre-agent-skills/blob/8974bdf57503d296c5bd015a406ae32a698cc605/skills/maplibre-tile-sources/SKILL.md),
SHA-256 `921b50ef93e2feb7801c30944e23cb9ff784f408f375fd95c48ea8fda01eb107`.
It was downloaded for review, not installed in the maintainer's agent configuration. It covers
rendering sources, tiles and sprites, with optional sibling references; it is not an authority
for analytical CRS, source fitness or correctness. Its scale thresholds are explicitly
heuristics, not acceptance criteria.

| Context | Contract review and required outcome |
|---|---|
| Relevant companion already installed | OMS composition rule 1 permits bounded rendering help. Keep the control's analysis and canonical outputs; interpret the companion's advice within its product scope. |
| Companion absent | Rule 2 provides authoritative-documentation fallback; rule 3 prohibits automatic bulk installation. Missing siblings cannot become required dependencies. |
| Discovery unavailable | Rule 2 explicitly permits local guidance and documentation. Uncertainty stays explicit; discovery is not a prerequisite for the bounded task. |
| Conflicting advice: “use EPSG:3857 for ground area” | Rule 4 preserves metric correctness. `formats-and-crs.md` expressly rejects Web Mercator ground-area measurement. Keep the control's analytical CRS and use rendering coordinates only for display. |

The four contexts have explicit guidance and a reviewed external scope. This establishes the
contract's intended response, not that a live agent follows it. Missing live companion evidence
remains recorded under the maintainer's live-trial closure; no paid test is silently added.

## Retained live dashboard: explicitly deferred in #69

The latest material output is retained at
`evals/results/20260926T062419Z/claude_code/001-basic-spatial-analysis/1/generated-project`.
Its historical eval passed, but the live case did not run `visual.*` assertions. Direct Chromium
review on September 26 found:

- No page errors. The three candidates render; all three individual layer toggles work.
  Tightening minimum area to 50,000 produces zero candidates; canonical reset restores 8,000 m²,
  2,000 m and three candidates. The exploratory label and provenance tab work.
- The manifest declares an Edit tab/draft tools, land-use multi-select, analysis/user-overrides
  group controls and semantic legend. The dashboard omits those features.
- At 390×844, the fixed 320-pixel sidebar leaves a 70-pixel-wide map.
- `visual.dashboard_loads_in_browser` reports `browser_check_error`: its reset procedure tries
  to uncheck inputs in an inactive tab. The checker also assumes particular control selectors.
  This automation limitation does not explain away the separately observed missing UI.

The browser initially lacked `libasound.so.2`; a locally extracted distro library made Chromium
launch without modifying system packages. Both attempts and the direct review are retained;
the final result is a substantive dashboard gap, not unavailable browser capability.

This is additional evidence beyond the already deferred QGIS map-layer source issue #67.
The maintainer explicitly deferred these dashboard/checker gaps in #69 and authorized publication.
Retain the original failures; fixture passes do not establish a pass for this live output.

## Publication checklist

- [x] Resolve or explicitly defer the live-dashboard gaps and retain this evidence (#69).
- [ ] Commit the release documentation and verify applicable CI on the final revision.
- [ ] Publish `v0.4.0` through the maintainer's GitHub release/PyPI workflow.
- [ ] Verify PyPI 0.4.0 and tag-pinned skills installation; record published artifact hashes.

This is the prepublication checklist. The GitHub release and its publishing workflow record
completion of publication; the release assets retain the final installation evidence.

The post-release plain-versus-skill comparison is deliberately outside this checklist. It needs
a separately agreed model, task, matched arms and budget; one pair is a case study, not proof of
general superiority over state-of-the-art models.
