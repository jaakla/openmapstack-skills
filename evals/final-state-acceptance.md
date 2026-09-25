# 0.4.0 final-state acceptance

Status: **fixed and corrected candidates not accepted; remaining trials run in this repository**.
This file records OpenMapStack's release gate. The remaining trials use this repository's runner
with the sandboxed Claude Code adapter ([ADR 0006](../docs/maintainers/decisions/0006-release-trials-in-repository-sandbox.md)).
The OpenMapBench trials below remain supporting evidence; generic benchmarking continues there.
Historical routing results remain in [the release record](../docs/release-0.4.0.md).

## Candidate and benchmark

- OpenMapStack: `e78bae896eb647cd436004b121b8659f34092ca6`, version 0.4.0.
- Exact wheel and full/subset snapshot hashes: [candidate evidence](../docs/acceptance-0.4.0-rc.json).
- OpenMapBench: `ba704e5fb968f0e97d10ca6a7c42888f824959d1` for the live set (review branch; not yet merged).
- Public development packs: `openmapstack-project` v1 (001, 070–073) and
  `openmapstack-routing` v1 (eight unhinted review tasks).
- Canonical [execution/review runbook](https://github.com/jaakla/OpenMapBench/blob/14409b3a9262b481bf9c806950e0eaf1363fbbe0/docs/openmapstack-acceptance.md).

Use retained wheel/snapshot bytes and a committed benchmark revision. A changed payload starts a
new acceptance set. The dirty QGIS worktree and historical mixed-payload trials are not this RC.
This is prepublication wheel acceptance, not evidence that 0.4.0 is already released on PyPI.

## Executed deterministic evidence (2026-09-23)

601 OpenMapStack unit tests passed with 46 optional-environment skips. Fixture evals passed
16/16 contract cases and detected 26/26 mutations; two contract assertions remain `not_testable`
and two soft gates remain unmet. OpenMapBench subsequently passed all 110 tests and Ruff, including its installed
wheel integration controls. The material-project control validates and cleanly reruns through the
public package; the Estonian known-answer control passes. Wrong CRS, mutated source, missing
pipeline, laundered validation and invented-feature controls fail with their intended stable codes.
These are harness/checker controls, not live-agent results. QGIS remains explicitly unavailable.

## Native trial outcome (2026-09-23)

A new **$10 aggregate cap** was explicitly authorized for `claude-sonnet-4-6`. The fixed set used
CLI 2.1.280, medium effort, an allowlisted rootless Bubblewrap runtime and the retained wheel/full
or subset snapshot. Preflight proved the intended mounts without a model request. Native activation
and raw provider events are retained; Bash read telemetry is partial. CLI builtins `design` and
`doctor` remained exposed despite the disable request and were not observed activated.

Nine attempts reported **$6.530115** in API-equivalent cost; **$3.469885** remains authorized. The
last attempt was rejected at the provider's organization monthly spend limit with zero usage/cost.
No further paid calls were made. This cost report is not an invoice. Both compilation caps overshot
slightly; the controller's aggregate safety reserve kept spending below the authorized total.

The negative lookup passed review. Collection SQL selected its specialist and repaired the supplied
query but added an inaccurate generalization; it was not executed. Discovery selected its specialist
but failed source/license/pinning review. Both compilation runs selected the owning specialist and
exhausted their per-trial budgets. All three material arms are unscorable: the v1 private grader
assumes output names/source IDs not specified by the public contract. Independent QGIS artifact,
Parquet metadata and checker errors are also recorded. No material clean rerun passed.

See the [trial review](https://github.com/jaakla/OpenMapBench/blob/14409b3a9262b481bf9c806950e0eaf1363fbbe0/docs/openmapstack-acceptance-20260923.md) and its hashed evidence index
for exact per-trial judgments and defect attribution. Native statuses and the frozen candidate
were preserved; no retrospective rubric changes or fixture-based live passes were applied.

## Corrected candidate outcome (2026-09-23)

The review above led to producer fixes `6d1e81b` (checker WKB/CRS handling) and `0749b07`
(licensing, building scope, pinning and PostGIS geography guidance). OpenMapBench v2 packs now
disclose every required delivery name. Focused trials against `0749b07` used the same harness:

- `chosen-engine-sql`: the geography claim was fixed. It still offers an equal-area CRS for
  distance work. `needs_review`.
- `bounded-discovery`: licensing, `tyyp` scope and content-hash pinning are correct. It made no
  provider lookup and claims without evidence that alternatives derive from ETAK. `needs_review`.
- `001-basic-spatial-analysis`: **failed** two required checks the task disclosed. Layers declared
  only an authority ID, and `cadastral_parcels` declared no `semantic_predicates`. The agent never
  activated a skill and inferred the contract from package source. `openmapstack validate` still
  reported all checks passed, because it kept a weaker copy of the layer-CRS check.

Follow-ups `908bf95` (fresh provider lookup; distance versus area CRS guidance) and `250c99c`
(`validate` delegates to `qgis.every_layer_declares_crs`) have no live evidence yet. Reported spend
is **$8.760220** of the $10 authorization; the remaining $1.239780 does not fit another material
trial with its reserve. See the [focused outcomes](https://github.com/jaakla/OpenMapBench/blob/feat/oms-release-acceptance/docs/openmapstack-acceptance-fixes-20260923.md#focused-live-outcomes).

## In-repository trials against `d4bfa5e` (2026-09-23)

A new authorization capped this round at $4.00 using `claude-sonnet-4-6` (Claude Code 2.1.281).
The candidate was frozen at `d4bfa5e`: collection content
`sha256:3f4d7b9da430c1f53cd65c4cc87189d25492febe6a5080903ff9bd6505df94b3`, the same skill payload
as `7b1a886`. Routing used local image `sha256:ab1c1835f312edd67d21b03e7ec75aba5a04c08e49e2c54367186288a0e52fe8`,
built from `evals/containers/routing.Dockerfile` on `node@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6`.
`d4bfa5e` also discloses the 001 artifact interface, whose earlier prompt hid the required names.

| Trial | Selection | Reviewed outcome | Status | Reported USD |
|---|---|---|---|---:|
| `chosen-engine-sql` (routing, collection) | `spatial-sql` | Passed: units, index use via matching expression index, duplicates, UTM projection for distance | `passed` | 0.135944 |
| `bounded-discovery` (routing, collection) | `geospatial-data-discovery` | Attempted three provider pages, which the harness refused; labeled those claims unverified. ETAK license, `tyyp` scope, pinning and paging correct. Wrong licenses for two alternatives, both from shipped guidance: Overture buildings are ODbL, Microsoft footprints CDLA-Permissive 2.0 | `not_testable` (`ToolSearch` telemetry gap) | 0.206338 |
| `001-basic-spatial-analysis` (live, sandboxed) | injected guidance | Not graded: harness defect refused almost every `Bash` command | setup failure (`error_max_budget_usd`) | 2.002112 |
| Sandbox tool check | — | `Bash`, DuckDB and `openmapstack` work after the fix | — | 0.037616 |

Record hashes: routing `3504530c…53ff35` (discovery), `20373d50…e874ed` (SQL); material agent
record `94a41843…e64c29`. Spend this round: **$2.382009 of $4.00**; $1.617991 remains, below one
material trial's cap. The material failure is a harness defect, not a skill result: the adapter had
relied on the maintainer's own tool allow rules, which the sandbox hides. `61bb27a` grants tools
explicitly; `bcb4131` stops counting `ToolSearch` and web tools as unattested skill reads. Neither
change regrades these trials. Routing still refuses `WebFetch`, so it cannot observe the fresh
provider lookup the discovery guidance now requires.

## Second in-repository round (2026-09-23)

A further **$10.00** was authorized for `claude-sonnet-4-6`. `5497c8d` let routing use web tools.
Each failure below traced to shipped guidance and was corrected before the next trial, so the
candidate moved: `7180e0e` (footprint licenses; `semantic_predicates` rule), then `cb4c009` (check
for the CLI; do not deliver while `validate` fails). Guidance regression tests guard each fix.

| Trial | Candidate | Selection | Reviewed outcome | Status | Reported USD |
|---|---|---|---|---|---:|
| material 001 (live) | `5497c8d` | injected | 35/36 required checks; zoning kept only as free-text `selection.filter` | failed `provenance.semantic_predicate_documented` | 1.986656 |
| `bounded-discovery` (collection) | `5497c8d` | passed | Live provider lookups; repeated the guidance's wrong Overture/Microsoft licenses | `passed` / needs review | 0.374675 |
| `bounded-discovery` (collection) | `7180e0e` | passed | Four live lookups, correct licenses, honest unverified PDF. Minor: unverified retention rationale | `passed` / passed | 0.293311 |
| `bounded-discovery` (discovery only) | `7180e0e` | passed | Read the license PDF; correct alternative licenses | `passed` / passed | 0.324528 |
| `ambiguous-architecture` | `7180e0e` | passed (`open-map-stack`) | Consequential questions and coupled choices | `passed` / passed | 0.076916 |
| `future-scale-architecture` | `7180e0e` | passed (`open-map-stack`) | Separates concurrent edits from pinned analytical snapshots at scale | `passed` / passed | 0.192059 |
| `casual-place-lookup` | `7180e0e` | passed (no GIS skill) | Brief and correct | `passed` / passed | 0.017089 |
| `material-analysis-generalist-only` | `7180e0e` | passed (single) | Complete plan; records land-use codes as `semantic_predicates`. Minor: unverified ETAK stop layer name | `passed` / passed | 0.413073 |
| material 001 (live) | `7180e0e` | injected | Predicates fixed; declared `parcel_area_range` but omitted it from the report. Never ran `validate`, which flags it | failed `validation.required_all_present` | 1.929765 |
| material 001 (live) | `cb4c009` | injected | Checked for the CLI, ran `validate`, was fixing its failures; about ten turns went on probing the runtime | setup failure (`error_max_budget_usd`, 70 turns) | 3.043631 |

Record hashes (SHA-256 prefix): material `a4403d5d`, `c94366d3`, `6df48698`; routing at `7180e0e`
`70e61a10` (collection discovery), `7ae36587` (standalone discovery), `bbb0e503`, `09f16719`,
`abd2e449`, `3f4c7f42`. `chosen-engine-sql` passed at `d4bfa5e`; `spatial-sql` content is unchanged
since. Round spend: **$8.651825 of $10.00**; $1.348175 remains, below one material trial.

Material 001 has not yet passed. The last trial shows the intended validate-and-repair loop, but
the prompt does not say which runtime exists (DuckDB Spatial and the CLI, no geopandas or `pip`),
so the agent spent turns probing it. Disclose the runtime in the 001 prompt, as OpenMapBench does,
before the next paid material trial, and allow a larger cap for the repair loop.

## Material 001 at `f142d95` (2026-09-24)

A further $4.50 was authorized. With the runtime stated in the prompt, material 001 **passed its eval**
at `f142d95` (skill payload identical to `cb4c009`): all 35 hard assertions, with `qgis.runtime_load`
soft and `not_testable`. The agent checked for the CLI, ran `validate`, fixed the two failures it
reported and delivered on a 30/30 `validate`. It used 49 turns and **$2.705749** (record `2ea24b65`).

Independent `openmapstack verify --rerun`, run inside the sandbox, still fails it. A runtime parameter
is bound to a field its step does not declare (`project.parameters_match_steps`). Neither `validate`
nor the 001 eval checked that. The clean rerun rebuilt equal outputs and a reproducible report, but
failed post-rerun validation, in part because the rerun copy had no README. Fixes:

- `9d2630c`: `validate` applies `verify`'s runtime-parameter rules, so the repair loop can see it.
- `60bbe14`: the clean-room rerun carries `README.md` as documentation.
- `4456691`: live clean reruns run in the sandbox rather than on the host, and live 001 now
  declares a clean rerun with the `rerun.*` assertions.

Replaying this delivered project through the updated runner fails only
`rerun.clean_execution_succeeded`, on the parameter defect. **Material 001 has therefore not
passed the full gate.** Round spend: $2.705749 of $4.50; the $1.794251 left does not cover another
material trial. The next one runs against a candidate frozen at or after `4456691`.

## Material 001 at `45063ca` (2026-09-24)

Candidate `45063ca` (`main` after #53 and #54; collection
`sha256:4dd248d87e3f54659077b4fcd8d97a0d3c3876751cae948a4beec9670b622937`). Material 001
**passed** all 35 hard assertions and the four `rerun.*` assertions. The clean rerun ran in the
sandbox, produced semantically equal outputs and reproduced the validation report.
`qgis.runtime_load` stayed soft and `not_testable`. The agent checked for the CLI, ran `validate`
and repaired what it reported: 44 turns, **$2.987357** at a $4.00 cap (record `25199bd4`).

Independent sandboxed `verify --rerun` found no failures; the earlier parameter defect did not
recur. Seven checks were `not_testable`: three need PyQGIS, and four outputs declare no EPSG code in
their format strings. The project reports `warning`, consistent with its own `not_testable`
QGIS runtime check.

The three PyQGIS checks were then run in the sandbox against the host's QGIS 3.40.15 (GDAL 3.12.2).
**All three failed.** The candidate layer points at GeoParquet, the Ubuntu GDAL build has no
Parquet or Arrow driver, and the map draws nothing. Shipped `qgis.md` blamed "an old GDAL"
instead. The follow-up adds `qgis.datasources_portable`, which warns on local layers outside an
allowlist of formats every GDAL build reads, and which `validate` reports as
`qgis.datasource_formats`. The QGIS guidance now requires
GeoPackage/GeoJSON/FlatGeobuf layers, and live 001 requires the check. One further material trial
must show agents follow it.

## Material 001 at `12fde5f` (2026-09-24)

Candidate `12fde5f` (collection `sha256:f9d5fe88cf56a24ce9ba353a1938f8e18da8ee742afc3d173a98f1ab538ce008`),
under a new $10 authorization. The portable-format rule held: `qgis.datasources_portable` passed,
and in the sandbox all three PyQGIS checks passed against the host's QGIS 3.40.15. Every layer
was valid, matched the manifest and rendered.

Material 001 **failed** `rerun.clean_execution_succeeded`. The agent built WGS84 GeoJSON layers for
the dashboard with one-off scripts, not the pipeline. It declared them as outputs, as `validate`
requires, and the pipeline hashes them in its run record. So the clean rerun crashed on a file the
pipeline never writes. The agent never ran a clean rerun; the guidance said to, without naming
`openmapstack verify project.yaml --rerun`. 63 turns, **$3.656927** (record `2357eb7d`).

Follow-up: both project skills now name that command and say every derived file must come from the
canonical pipeline.

## Material 001 at `70d110a` (2026-09-24)

Candidate `70d110a` (collection `sha256:4f55897533424d005de4fb7828c5c763cdfcebbd0ddb34eba11a0b4dc25f206c`).
Material 001 **passed its eval**: every hard assertion, including `qgis.datasources_portable` and
the four `rerun.*` assertions from the sandboxed clean rerun. 57 turns, **$3.048889** (record
`341de3ae`). The agent ran `validate` and `verify`, not `verify --rerun`.

Independent checks found two more issues. Sandboxed `verify --rerun` failed
`rerun.outputs_semantically_equal` on the GeoPackage output; its features were identical and only
`gpkg_contents.last_change` differed. That was a comparator defect, since GeoPackage was compared
by bytes. The real-QGIS render check failed: roads and POI GeoJSON were WGS84 but declared
EPSG:3301, so QGIS drew them near the grid's origin.

Follow-ups:
- GeoPackage outputs are compared semantically.
- New `qgis.layer_crs_matches_data` (in `validate` as `qgis.layer_crs_data`) fails a declared CRS
  that contradicts the data. Live 001 asserts it, and the QGIS guidance states the rule.
- The review also found absolute datasource paths in the committed NYC project (#54).
  `qgis.static_valid` now fails absolute paths, and the example writes relative ones.

Round spend so far: $6.705816 of the $10 authorization.

## Round at `b65a2b4` (2026-09-24)

A new **$20** authorization. Candidate `b65a2b4` (`main` after #59; collection
`sha256:6f9dad1290f3fd6656711c6e3f31e4ee0ec6a3797953058fdb2a7e5982ee1dcd`), `claude-sonnet-4-6`,
Claude Code 2.1.281. Routing used local image `sha256:01cd8a23c12db638fbf58873c36a603228ccd17fdf1ade6f020cd5839ddfcdbb`,
rebuilt from `evals/containers/routing.Dockerfile` on the same pinned Node base with Codex 0.156.1.
The maintainer reviewed task outcomes; verdicts below are theirs.

| Trial | Selection | Reviewed outcome | Verdict | Reported USD |
|---|---|---|---|---:|
| material 001 (live) | injected | All hard and `rerun.*` assertions; delivered P1, P2, P5. Ran `validate` and repaired, not `verify --rerun`. 54 turns | passed | 3.375187 |
| `chosen-engine-sql` (collection) | `spatial-sql` | Units, `ST_DWithin`, matching expression index, `DISTINCT`, plan check. Unexecuted | passed | 0.113604 |
| `chosen-engine-sql` (`spatial-sql` alone) | `spatial-sql` | Correct core. Proposed an arbitrary UTM zone for data of unknown extent, and wrongly said a plain index serves an `ST_Transform` predicate | needs review | 0.113567 |
| `bounded-discovery` (collection) | `geospatial-data-discovery` | Five live lookups; unreadable license PDF labelled unverified. GPKG listed though the live page offers SHP/TAB/DGN/DWG (from shipped `data-sources.md`). OSM/Overture "derive from" ETAK has no cited source | passed with notes | 0.301924 |
| `compile-existing-analysis` (collection) | `reproducible-gis-project`; `not_testable` (Bash read surface) | Algorithm kept; missing source details listed, not invented; honest that nothing ran. Unexecuted scaffold; extra outputs; pins unpublished `openmapstack==0.4.0` | needs review | 1.422498 |
| `billion-row-architecture` (collection) | `open-map-stack` | Sound overall architecture. Partitions on a `country_iso` column Overture buildings lack; H3 resolution 3 stated as ~1,000 cells (it has 41,162); pins a 2025 release while warning that only recent ones are retained | pending | 0.395723 |

Record hashes (SHA-256 prefix): material `9e5faa71` (agent), `9589b565` (grading); routing
`2ace0d7d`, `4a07d100`, `0e1009c3`, `e8ecf94b`, `17f4523e`, in table order.

Independent sandboxed `verify --rerun` of the delivered 001 project, with the host's QGIS 3.40.15:
47 passed, 0 failed. All four PyQGIS checks passed, including `qgis.layer_crs_matches_data` and
`qgis.every_declared_layer_renders`. The one `not_testable` check is a candidate format string with
no EPSG code. The sandbox must also expose `/etc/alternatives`, or PyQGIS fails to load `libblas`
and those checks report `not_testable`.

Maintainer notes: Maa-amet data underlies both ETAK and, through community imports, parts of
Estonian OSM, but no public lineage record documents it, so the claim stays uncited. For lon/lat
data, geography on the spheroid is correct at any extent; a local projected CRS fits only a known
small area. `8e289e7` makes that the `spatial-sql` default. Rerun at `8e289e7`, the same case
chose geography because "the data extent is unspecified" when installed alone ($0.140620, record
`e0613e96`), and offered a projected CRS only for a confirmed extent in the collection
($0.118739, `86e788d3`). Both passed selection and the reviewed criterion.

Round spend: **$5.981862 of $20.00**. Cases 070–073 were not run: their prompts state neither the
runtime nor, for 071–073, the full project they are graded on.

## Running the remaining trials

Freeze a clean candidate at or after `250c99c` and confirm a new spend authorization first.
Executed projects (guidance injected; the agent runs sandboxed; the cap is per trial):

```bash
python3 evals/run.py --mode live --agent claude_code --model claude-sonnet-4-6 \
  --collection --arms oms --case 001-basic-spatial-analysis \
  --max-budget-usd 2 --credential-file ~/.claude/.credentials.json --timeout 1200
```

Native selection (Docker, digest-pinned image; the cap is split across the selected cases; see
[routing smoke tests](routing.md)):

```bash
python3 evals/run.py routing --agent claude_code --model claude-sonnet-4-6 \
  --image sha256:EXACT_LOCAL_IMAGE_ID --profile collection \
  --case bounded-discovery --case chosen-engine-sql --max-budget-usd 1 \
  --credential-file ~/.claude/.credentials.json --out evals/results/routing-EXACT_RUN_ID
```

Project trials here do not measure native activation on an executed task. Selection is judged by
the routing cases; review outcomes and actual execution separately as below.

## Remaining release gates

- Repair and version the material artifact contract/checker coverage before another paid material
  comparison. Fix discovery guidance/source verification and substantiate task quality. Any changed
  producer payload requires a newly frozen candidate, not reuse of this candidate's evidence.
- Provider access is restored. Further paid trials need a new authorization; carry the recorded
  $8.760220 forward if they continue the existing one.
- Done at `b65a2b4`: `chosen-engine-sql`, `bounded-discovery` and material 001, which passed its
  required checks and clean rerun. `8e289e7` changes only `spatial-sql` guidance, so the release
  candidate must still be refrozen and this evidence carried forward or rerun.
- Run 070–073 after their prompts state the runtime and the project they are graded on. Standalone
  SQL and compilation were attempted at `b65a2b4` and need review; `billion-row-architecture` awaits
  a verdict. Plain/skill material comparison evidence remains incomplete.
- Review selection, useful task outcome and actual execution separately. Text tasks remain
  `needs_review`; self-reported activation or an unexecuted scaffold is not acceptance evidence.
- Review installed/absent companion, unavailable discovery and conflicting product-advice contexts
  against one validated project and a reviewed, pinned external payload.
- Run relevant QGIS/browser checks in capable runtimes. Resolve substantive failures against a
  newly fixed candidate; do not weaken criteria or count unavailable checks as passing.
- Recheck hosted CI/release installation for any changed payload and publish only after acceptance.

OpenMapBench #2 remains open for generic live comparison, provider/telemetry parity and historical
evidence migration. The release gate does not wait on it.
