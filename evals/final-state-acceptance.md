# 0.4.0 final-state acceptance

Status: **fixed candidate; deterministic integration verified; live acceptance pending**.
OpenMapBench owns execution, task packs, SUT provenance, repeats and result bundles. This file
records OpenMapStack's release gate; it is not another benchmark runner or independently evolving
case definition. Historical routing results remain in [the release record](../docs/release-0.4.0.md).

## Candidate and benchmark

- OpenMapStack: `e78bae896eb647cd436004b121b8659f34092ca6`, version 0.4.0.
- Exact wheel and full/subset snapshot hashes: [candidate evidence](../docs/acceptance-0.4.0-rc.json).
- OpenMapBench: `911c72fc3113ae390cbce105d72c11e150e04840` (review branch; not yet merged).
- Public development packs: `openmapstack-project` v1 (001, 070–073) and
  `openmapstack-routing` v1 (eight unhinted review tasks).
- Canonical [execution/review runbook](https://github.com/jaakla/OpenMapBench/blob/911c72fc3113ae390cbce105d72c11e150e04840/docs/openmapstack-acceptance.md).

Use retained wheel/snapshot bytes and a committed benchmark revision. A changed payload starts a
new acceptance set. The dirty QGIS worktree and historical mixed-payload trials are not this RC.
This is prepublication wheel acceptance, not evidence that 0.4.0 is already released on PyPI.

## Executed deterministic evidence (2026-09-23)

601 OpenMapStack unit tests passed with 46 optional-environment skips. Fixture evals passed
16/16 contract cases and detected 26/26 mutations; two contract assertions remain `not_testable`
and two soft gates remain unmet. OpenMapBench passed 107 tests and Ruff, including its installed
wheel integration controls. The material-project control validates and cleanly reruns through the
public package; the Estonian known-answer control passes. Wrong CRS, mutated source, missing
pipeline, laundered validation and invented-feature controls fail with their intended stable codes.
These are harness/checker controls, not live-agent results. QGIS remains explicitly unavailable.

## Remaining release gates

- Establish a new paid budget and exact model/harness/runtime configuration. The earlier cumulative
  $5 authorization is not renewed. No paid trials were run in this acceptance preparation.
- Verify the isolated native-discovery provider wrapper and raw-event normalization. This session
  cannot access the Docker socket. Generic OpenMapBench staging is not an OS sandbox.
- Execute the runbook's predeclared 17-trial set: collection routing, each bounded specialist alone,
  generalist-only planning, executed 001 under collection/generalist/plain, and 070–073.
- Review selection, useful task outcome and actual execution separately. Text tasks remain
  `needs_review`; self-reported activation or an unexecuted scaffold is not acceptance evidence.
- Review installed/absent companion, unavailable discovery and conflicting product-advice contexts
  against one validated project and a reviewed, pinned external payload.
- Run relevant QGIS/browser checks in capable runtimes. Resolve substantive failures against a
  newly fixed candidate; do not weaken criteria or count unavailable checks as passing.
- Finish hosted CI/release installation checks and maintainer publication after acceptance.

OpenMapBench #2 remains open for live comparison, provider/telemetry parity and historical evidence
migration. Retain the transitional OpenMapStack adapters/workflow until that parity is demonstrated.
