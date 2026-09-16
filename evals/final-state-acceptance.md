# 0.4.0 final-state acceptance

Status: **prepared, not executed with a live agent**. This is a small release
review using the existing runner and real task outputs. It adds no paired
before/after gate. The old monolith was not a validated quality oracle.

## Proposed execution scope

Use one trial per case on the final committed payload. Start with the existing
Claude Code adapter and `claude-sonnet-4-6`; record the exact CLI version and
container digest. Native selection uses `routing --profile collection` and its
unhinted prompts. The three bounded cases also run with only their owning skill
installed. Use the single profile for the generalist-only material case.

Confirm the final trial selection and available spend before paid execution.
The earlier $5 authorization was cumulative, and one timed-out historical trial
has unknown final cost. No new budget is assumed. Do not run the entire matrix
repeatedly or extend a failed trial without checking remaining budget.

## Judge the answer against the task

| Existing routing case | Useful outcome to inspect |
|---|---|
| `bounded-discovery` | Authoritative source and actual coverage/feature meaning; license and immutable pin strategy; a way to check completeness; no invented availability or unnecessary project scaffold. Check provider claims against current authoritative metadata. |
| `chosen-engine-sql` | Recognize geometry degrees versus metre distance, correct geodesic/projected predicate, explain an index compatible with that expression, and resolve duplicate parcel IDs from multiple stops. No engine migration or full project required. |
| `compile-existing-analysis` | Preserve the supplied algorithm/stack, produce a usable manifest/pipeline scaffold, identify unavailable source details and retain executable correction, validation and rerun requirements. Do not report an unexecuted scaffold as a validated project. |
| `ambiguous-architecture` | Resolve consequential context and explain coupled source/compute/storage/delivery choices. Specialist activity must support the architecture rather than independently imposing incompatible tools. |
| `billion-row-architecture` / `future-scale-architecture` | Consider data access, future scale, concurrency, partitioning, operational cost and browser delivery; avoid choosing solely from today's row count. Use one of these as the scale stress case initially. |
| `casual-place-lookup` | Answer accurately and briefly without loading GIS skills. |
| `material-analysis-generalist-only` | Preserve the full reproducible-project obligations with only the generalist installed; absence of specialists does not justify skipping them. This prompt tests planning, not an executed analysis. |

For an executed material result, use existing live case
`001-basic-spatial-analysis` with `--collection --skill-mode enabled`, then with
`--collection --skill open-map-stack --skill-mode enabled`. Evaluate the supplied
known-answer input, manifest, immutable sources, metric CRS, canonical pipeline,
validation and clean rerun with the existing semantic checks. This is two
final-state installation configurations, not a historical comparison. Use the
existing controlled mutation cases as checker failure evidence; do not ask a
model to invent an oracle or grade its own answer.

Review the artifact and actual command results, not just narrative. Record
`passed`, `failed` or `not_testable` with a concrete reason and an evidence path
for selection, task outcome and execution separately. A corrected query that
was only reviewed must be labelled unexecuted. A model's claim to have selected
a primary skill does not replace native event evidence. Missing runtime or
telemetry stays visible. Release acceptance requires resolving substantive
failures; a routing pass alone is insufficient.

## Optional companion composition review

Use a small MapLibre presentation task with an already chosen analytical stack:
“Configure a MapLibre view of these validated analysis outputs, preserving the
manifest's layers, attribution and metric-analysis results.” Supply the same
small project for each context. These contexts test policy, not vendor prompts:

| Context | Setup and expected observation |
|---|---|
| Installed companion | Install a reviewed, pinned `maplibre-tile-sources` payload in the isolated workspace using existing authorization; retain its revision/hash. Observe bounded rendering help while OMS retains analytical meaning, provenance and reproducibility. |
| Absent companion | Only OMS is installed. Complete the bounded work using local guidance and authoritative product docs, or state a real limitation; no automatic third-party installation. |
| Discovery unavailable | Same absence, with no skill-discovery tool. Do not invent a skill or block useful work solely because discovery is unavailable. |
| Conflicting product advice | Add an explicitly synthetic fixture note recommending EPSG:3857 for measuring ground area because the map uses it. Reject that analytical recommendation, retaining a suitable metric/equal-area method while allowing 3857 for display. This is a controlled conflict fixture, not a claim about MapLibre's real guidance. |

Do not make these four contexts a new benchmark framework. Review them in the
final acceptance session, retaining prompt, installed inventory, response and
observable actions. External product authority was checked in the installed
[companion reference](../skills/open-map-stack/references/companion-skills.md).

## Evidence record

For each reviewed result retain: commit and payload hash, case/configuration,
model/adapter/runtime, input evidence, output/evidence path, selection status,
task status, execution limitations, reported cost and reviewer conclusion.
Keep generated trial outputs outside commits unless intentionally selecting a
small evidence bundle. QGIS/browser checks run only in their capable runtime;
fixture checks cannot stand in for live or visual evidence.
