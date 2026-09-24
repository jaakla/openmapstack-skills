# OpenMapBench interoperability contract

OpenMapBench owns benchmark orchestration, run isolation, provider/model execution,
benchmark task and pack governance, repeated trials, system-under-test provenance,
reporting, cost/reliability metrics, holdouts and certification policy.

OpenMapStack owns the OpenMapStack project contract, the checks that grade a
produced OpenMapStack project, connector/product semantics, and the exact identity
of the skill/collection payload it publishes.

> OpenMapStack defines what an OpenMapStack project means. OpenMapBench decides
> how systems are compared.

Neither side copies the other's implementation. OpenMapBench consumes a released
`openmapstack` package through the API below. Generic live benchmarking under
`evals/` is transitional until parity exists in
[OpenMapBench #2](https://github.com/jaakla/OpenMapBench/issues/2). OpenMapStack's
own release trials stay here
([ADR 0006](maintainers/decisions/0006-release-trials-in-repository-sandbox.md)).

OpenMapStack-owned code for this boundary:
`openmapstack/api.py`, `openmapstack/schemas/`, and the skill/collection snapshot
producer in `openmapstack/snapshot.py` / `openmapstack/collection.py`.

The consumer fixture that proves the check interface without vendoring an
implementation is `tests/test_check_api.py::ConsumerFixtureTests`.

## 1. Versioned check API — `openmapstack-check-api/v1`

| Surface | Purpose |
|---|---|
| `openmapstack api-info --json` / `openmapstack.api.api_info()` | package version, check API version, project schema, result schemas, status vocabulary, dimensions |
| `openmapstack api-info --require-api … --min-version … --require-check …` / `negotiate()` | compatibility answer with every unmet requirement listed |
| `openmapstack checks --json` / `list_checks()` | check catalogue: name, module, dimension, `oracle_free`, parameters |
| `openmapstack check NAME WORKSPACE --arg k=v --json` / `run_check()` | one check, one versioned result |
| `openmapstack verify PROJECT --json` | the whole applicable verification plan |

`openmapstack/api.py` is the authoritative statement of this; the summary
here must not be read as widening it. Three things are additive and retain the
major: a new check, a new **optional** parameter, and a new result field.
Everything else is an incompatible revision — renaming or removing a check,
changing a parameter's meaning, changing the four-state status vocabulary, and
**adding a required parameter**.

That last one is worth spelling out because it fails quietly in the direction
of looking fine: a pack that pinned the major would still negotiate
successfully, and then `run_check()` would reject every call for the missing
argument. A required parameter is a new contract, not an addition to the old
one.

OpenMapBench pins the API major and minimum released package version used by a
benchmark pack.

## 2. Result semantics a consumer may rely on

A single check result validates against `openmapstack-check-result/v1`; a whole
verification validates against `openmapstack-verify-result/v1`. Both schema
identifiers are reported by `api-info`, and both live in
`openmapstack/schemas/` — pin them rather than inferring the shape from an
example payload.

- `status` is one of `passed | failed | warning | not_testable`.
- A check that could not establish its predicate is never `passed`.
- `code` is the stable machine identifier for non-pass outcomes. Grade on
  `status` and `code`, never on prose in `detail`.
- `dimension` identifies the evidence bucket; dimensions do not become one
  opaque weighted quality score.
- `oracle_free: false` identifies checks that need independent expected truth.
- A checker exception is represented honestly as unavailable/not-testable
  evidence rather than a pass.

OpenMapBench decides benchmark admissibility and denominators. An unavailable
required checker may make a benchmark run unscorable/setup-failed without
changing OpenMapStack's project-QA semantics.

## 3. Skill/collection identity is produced by OpenMapStack

OpenMapStack knows which bytes constitute its distributable skill or collection,
so it owns the snapshot producer.

Examples:

```bash
openmapstack skill-snapshot --source . --out /tmp/oms-collection --json
openmapstack skill-snapshot --source . --skill open-map-stack --out /tmp/oms-subset --json
openmapstack skill-snapshot --format v2 --source /path/to/installed-skill --out /tmp/oms-installed --json
openmapstack skill-snapshot --inspect /tmp/oms-collection --json
```

The snapshot records selected skills, entry points, file hashes and aggregate
content identity, and rejects unsafe paths/symlinks.

This is **producer-side capability identity**, not the whole benchmark arm.

OpenMapBench consumes the snapshot manifest/hash as one component of its generic
system-under-test descriptor.

## 4. System-under-test / arm provenance belongs to OpenMapBench

A published benchmark result identifies the complete tested configuration, not
only a skill hash.

OpenMapBench owns the native representation for at least:

```text
agent/harness + version
model/provider + exact id/revision where known
reasoning/sampling configuration
skill/capability payloads + versions/hashes
tool/MCP surface
openmapstack package/check API version when used
task pack/version + task/data hashes
runtime/container
repeat count / seed where supported
price catalog date
```

The historical `openmapstack-benchmark-arm/v1` and `v2` schemas under
`evals/schemas/` remain readable as migration evidence until OpenMapBench #2
defines/imports the replacement. They are **not the long-term canonical schema**.

Do not extend those historical arm schemas with new benchmark concepts unless
needed strictly for backward compatibility.

## 5. OpenMapStack project output is graded through the released package

Some benchmark cases produce a complete OpenMapStack project directory rather
than one scalar/table/vector artifact.

The target flow is:

```text
OpenMapBench task + frozen fixtures
        ↓
system under test
        ↓
generated OpenMapStack project
        ↓
released openmapstack package
        ↓
openmapstack verify/check API
        ↓
stable result status/code
        ↓
OpenMapBench run evidence
```

OpenMapBench retains the generated project, execution evidence and benchmark
manifest. OpenMapStack supplies project-specific checking only.

The benchmark must not expose expected assertions, reference projects, mutation
generators or hidden rationale to the system under test.

## 6. Task ownership

Behavioral cases 070–073 are canonical OpenMapBench migration candidates:

- underspecified request;
- contradictory request;
- do-not-invent/missing attribute;
- non-English GIS request.

Their source definitions and mini-Tartu inputs have moved into the OpenMapBench
migration branch under `benchmark/candidates/openmapstack-project/`.

Until OpenMapBench #2 implements project-directory/check-API grading, the
existing copies here may remain as a **transitional scheduled integration smoke**.
They must not evolve into a competing independent public benchmark.

Future benchmark task changes happen in OpenMapBench first. Any retained
OpenMapStack smoke should pin/reference a released task/pack version.

## 7. Routing/discovery ownership

OpenMapStack tests that its published metadata, collection descriptor and
standalone payloads are valid and discoverable.

OpenMapBench owns substantive routing experiments:

- positive/negative/composition cases;
- false/excess activation;
- native discovery across agent harnesses;
- provider telemetry normalization;
- plain-vs-skill comparison;
- repeated trials and reliability/cost evidence.

See OpenMapStack #32 and OpenMapBench #2.

## 8. Evidence classes

OpenMapBench may distinguish authoritative answers, frozen expert references,
metamorphic evidence and differential diagnostics.

OpenMapStack checks remain explicit about what they establish. A VLM or semantic
judge must never turn an analytically unverified result into a deterministic
correctness pass.

## 9. Migration rule

Do not delete the historical OpenMapStack benchmark harness merely because
ownership changed on paper. Removal happens only after OpenMapBench can reproduce
the required behavioral/routing evidence.

Migration order:

1. OpenMapBench project/check-API integration.
2. Canonical 070–073 tasks in OpenMapBench.
3. Generic OpenMapBench SUT provenance replacing arm v1/v2 for new evidence.
4. Routing/discovery benchmark parity.
5. One reproducible plain-vs-OpenMapStack comparison through OpenMapBench.
6. Deprecate/remove provider adapters, live benchmark workflow and generic live
   orchestration from OpenMapStack while retaining checker/mutation CI.

Canonical migration tracker:
[OpenMapBench #2](https://github.com/jaakla/OpenMapBench/issues/2).
