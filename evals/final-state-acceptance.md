# 0.4.0 final-state acceptance

Status: **fixed candidate not accepted; native trials recorded; provider access blocked**.
OpenMapBench owns execution, task packs, SUT provenance, repeats and result bundles. This file
records OpenMapStack's release gate; it is not another benchmark runner or independently evolving
case definition. Historical routing results remain in [the release record](../docs/release-0.4.0.md).

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

## Remaining release gates

- Repair and version the material artifact contract/checker coverage before another paid material
  comparison. Fix discovery guidance/source verification and substantiate task quality. Any changed
  producer payload requires a newly frozen candidate, not reuse of this candidate's evidence.
- Restore provider access before further paid trials, carrying the recorded spend forward under
  the same authorization. The remaining budget may not cover all missing evidence.
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

OpenMapBench #2 remains open for valid live comparison, provider/telemetry parity and historical
evidence migration. Retain transitional OpenMapStack adapters/workflow until parity is demonstrated.
