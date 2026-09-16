# OpenMapBench interoperability contract

OpenMapBench owns benchmark orchestration, run isolation, provider adapters,
leaderboard policy, and task governance. OpenMapStack owns the project
contract and the checks that grade a produced project. This document is the
narrow surface between them. Neither side copies the other's implementation:
OpenMapBench consumes a released `openmapstack` package through the API
below; OpenMapStack does not export a second benchmark harness.

Owning code: `openmapstack/api.py`, `openmapstack/schemas/`,
`openmapstack/snapshot.py`, `evals/schemas/benchmark-arm-v1.schema.json`.
The consumer fixture that proves the contract without vendoring a check is
`tests/test_check_api.py::ConsumerFixtureTests`.

## 1. Versioned check API — `openmapstack-check-api/v1`

| Surface | Purpose |
|---|---|
| `openmapstack api-info --json` / `openmapstack.api.api_info()` | package version, check API version, project schema, result schemas, status vocabulary, dimensions |
| `openmapstack api-info --require-api … --min-version … --require-check …` / `negotiate()` | compatibility answer with every unmet requirement listed; exit 1 when incompatible |
| `openmapstack checks --json` / `list_checks()` | the catalogue: name, module, dimension, `oracle_free`, parameters with required/default |
| `openmapstack check NAME WORKSPACE --arg k=v --json` / `run_check()` | one check, one `openmapstack-check-result/v1` record |
| `openmapstack verify PROJECT --json` | the whole applicable plan, `openmapstack-verify-result/v1` |

Additive changes (a new check, a new optional parameter, a new result
field) keep the major. Renaming or removing a check, changing a parameter's
meaning, or touching the four-state vocabulary bumps it. A consumer pins the
major and the minimum package version it was tested against.

## 2. Result semantics a consumer may rely on

- `status` ∈ `passed | failed | warning | not_testable`; a check that could
  not establish its predicate is never `passed`.
- `code` is a stable machine identifier whenever `status` is not `passed`.
  Grade on `status` and `code`; never on `detail` text.
- `dimension` names the reporting bucket (`gis_correctness`,
  `reproducibility_compliance`, `provenance`, `override_handling`,
  `validation_integrity`, `presentation_contract`, `rerun_success`,
  `metamorphic_evidence`, `visual_judgement`). Buckets have separate
  denominators and are never collapsed into one score. Deterministic
  analytical correctness, metamorphic evidence, differential diagnostics,
  and visual judgement stay apart.
- `oracle_free: false` marks the five known-answer checks. On arbitrary
  data they are reachable only through attested `validation.expectations`;
  a benchmark with a frozen expert reference may call them directly.
- A check that raises is `not_testable` with `code: check_error`. A
  harness keeps such trials **outside the scored denominator** and reports
  them prominently as setup failures, exactly as `evals/run.py` does
  (`status: setup_failed`, exit 2).

## 3. Reproducible arms — `openmapstack-benchmark-arm/v1`

A published benchmark result identifies the *whole arm*, not a skill hash.
`evals/schemas/benchmark-arm-v1.schema.json` is the record OpenMapBench
must store per arm:

| Field | Meaning |
|---|---|
| `arm` | `plain` (no skill) or `oms` (skill snapshot injected) |
| `skill` | mode, snapshot content hash, repository commit, dirty flag |
| `task_set` | case ids and a content hash over their prompts, expectations, and declared fixtures |
| `checker` | `openmapstack` package version and check API version |
| `harness` | harness repository commit and dirty flag |
| `runtime` | Python version, platform, DuckDB version, container image if any |
| `tool_surface` | adapter name and the exact agent CLI/API version it drove |
| `model` | provider, exact model id, provider revision/alias resolution when known |
| `sampling` | seed, temperature, reasoning configuration as the adapter reports them (nulls are allowed but must be present) |
| `price_catalog_date` | the date of the price list used for cost estimates |

`openmapstack skill-snapshot --format v1 --source SKILL_ROOT --out DIR --json` produces the controlled
copy of `SKILL.md`, `references/`, and `templates/` with a per-file
inventory and content hash (`openmapstack-skill-snapshot/v1`); `--inspect`
re-verifies one. Symlinks and paths escaping the snapshot root are rejected.

### Collection migration in 0.4.0: snapshot v2 and arm v2

`api-info` advertises `skill_snapshot_schemas` and `benchmark_arm_schemas`.
Consumers must check the required schema identifier and pin a compatible
package version; do not reinterpret a v1 record as a collection. The project
schema and check API remain v1.

```bash
openmapstack skill-snapshot --source . --out /tmp/oms-collection --json
openmapstack skill-snapshot --source . --skill open-map-stack --out /tmp/oms-subset --json
openmapstack skill-snapshot --format v2 --source /path/to/installed-skill --out /tmp/oms-installed --json
openmapstack skill-snapshot --inspect /tmp/oms-collection --json
```

A collection source (`collection.json`) defaults to v2; a legacy skill root
defaults to v1. V2 copies the complete selected skill directories, including
agent metadata, templates, schemas and worked-example sources, under `skills/`.
Its manifest records skill names, descriptions, entry points, one coordinated
version, per-file hashes and an aggregate hash. The generated `collection.json`
describes only the selected subset. Inspection accepts both versions and checks
missing/extra/changed files, unsafe paths, symlinks and descriptor consistency.

`evals/run.py --mode live --collection [--skill NAME ...]` uses snapshot v2 and
`openmapstack-benchmark-arm/v2`. This is **injection**, not native discovery.
V2 adds `configuration`: `kind` (`plain`, `legacy_single`, `collection`),
`delivery` (`none`, `injection`, `discovery`), snapshot schema, selected skill
descriptors and content hash. An unknown hash remains null after setup failure.
The model/runtime/task/checker provenance fields remain required. External
discovery harnesses use `delivery=discovery` with their actual adapter evidence.
The historical runner path without `--collection` continues to emit v1.

The small native runner remains a v1 single-skill smoke path until the final
collection integration in #39. Its entry point now defaults to
`skills/open-map-stack`; historical exported roots remain valid explicit sources.

## 4. Task ownership and paired arms

`evals/run.py --export-tasks DIR` writes the vendor-neutral task bundles
(`openmapstack-benchmark-task/v1`: prompt, declared fixtures, assertions,
hard gates, task hash) that OpenMapBench imports. Cases 070–073 (the
behavioural, prompt-style tasks) are exported as canonical OpenMapBench
tasks; this repository keeps them only as a scheduled smoke subset that
protects the integration and does not publish a competing benchmark.

`evals/run.py --mode live --arms paired` runs `plain` and `oms` over the
same cases, trials, and seeds and reports them side by side: task parity,
per-arm success rate with a Wilson interval, per-arm median cost, tokens,
and duration, and trajectory diagnostics (event counts). It never emits a
single "success per dollar" number; quality and cost are reported as a
trade-off, and headline correctness is artifact-first.

## 5. Evidence classes

OpenMapBench distinguishes four evidence classes rather than one ground
truth: an authoritative answer, a frozen expert reference, metamorphic
evidence, and a differential diagnostic. Only the first two license a
known-answer check. VLM/visual review has its own denominator and judge
provenance and never turns an unverified analytical result into a pass.
