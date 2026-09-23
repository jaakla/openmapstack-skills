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
| `bounded-discovery` (routing, collection) | `geospatial-data-discovery` | Attempted three provider pages, which the harness refused; labeled those claims unverified. ETAK license, `tyyp` scope, pinning and paging correct. Wrong licenses for two alternatives: Overture buildings and Microsoft footprints are ODbL | `not_testable` (`ToolSearch` telemetry gap) | 0.206338 |
| `001-basic-spatial-analysis` (live, sandboxed) | injected guidance | Not graded: harness defect refused almost every `Bash` command | setup failure (`error_max_budget_usd`) | 2.002112 |
| Sandbox tool check | — | `Bash`, DuckDB and `openmapstack` work after the fix | — | 0.037616 |

Record hashes: routing `3504530c…53ff35` (discovery), `20373d50…e874ed` (SQL); material agent
record `94a41843…e64c29`. Spend this round: **$2.382009 of $4.00**; $1.617991 remains, below one
material trial's cap. The material failure is a harness defect, not a skill result: the adapter had
relied on the maintainer's own tool allow rules, which the sandbox hides. `61bb27a` grants tools
explicitly; `bcb4131` stops counting `ToolSearch` and web tools as unattested skill reads. Neither
change regrades these trials. Routing still refuses `WebFetch`, so it cannot observe the fresh
provider lookup the discovery guidance now requires.

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
- Rerun `chosen-engine-sql`, `bounded-discovery` and material 001 against a candidate frozen at or
  after `250c99c`. Material 001 must pass its required checks and clean rerun.
- Complete the eight unattempted planned trials: standalone discovery, ambiguous/future-scale
  architecture, generalist-only planning and 070–073. Standalone SQL needs a real attempt;
  compilation and material clean-rerun/comparison evidence remain incomplete.
- Review selection, useful task outcome and actual execution separately. Text tasks remain
  `needs_review`; self-reported activation or an unexecuted scaffold is not acceptance evidence.
- Review installed/absent companion, unavailable discovery and conflicting product-advice contexts
  against one validated project and a reviewed, pinned external payload.
- Run relevant QGIS/browser checks in capable runtimes. Resolve substantive failures against a
  newly fixed candidate; do not weaken criteria or count unavailable checks as passing.
- Recheck hosted CI/release installation for any changed payload and publish only after acceptance.

OpenMapBench #2 remains open for generic live comparison, provider/telemetry parity and historical
evidence migration. The release gate does not wait on it.
