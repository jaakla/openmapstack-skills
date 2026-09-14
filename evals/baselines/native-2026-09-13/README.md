# Native discovery evidence for #32 and #33

`summary.json` records eleven trials using Claude Code 2.1.270 and
`claude-sonnet-4-6` in the pinned isolated image described in the report:

| Group | Selection passed | Selection failed | Not testable |
|---|---:|---:|---:|
| Pre-refactor baseline, eight cases | 2 | 3 | 3 |
| After the project-workflow extraction, two focused cases | 0 | 2 | 0 |
| Initial runtime pilot, excluded from routing counts | 0 | 0 | 1 |

The source-discovery case invoked the skill and read its source reference. The
casual lookup correctly consumed no skill. SQL, ambiguous architecture and
billion-row architecture missed activation. Compilation hit its trial budget,
the future-scale trace included opaque Bash reads, and the material-analysis
baseline timed out; these three cases remain `not_testable`. Both post-change
cases (SQL and material-analysis planning) missed activation.

This small sample establishes observable baseline gaps, not four-way routing
precision, analytical correctness or a statistical non-regression conclusion.
The project workflow's **verbatim preservation** is proved separately by the
migration test and deterministic fixture suite; these live traces do not prove
successful project delivery after the wording change. Keep #32/#33 open until
their remaining behavioral acceptance is addressed.

The first pilot used a mismatched container UID and could not read the staged
skill. The startup inventory exposes that failure. It is excluded from routing
counts and included in cost. The corrected runner checks entry-point readability
and discovery inventory and uses the invoking user's UID.

## Audit and costs

Each compressed `*.events.json.gz` contains the captured event array; observation
indices in the summary address that array. Raw event hashes refer to decompressed
bytes. Prompts, their hashes, source snapshot hashes, CLI/model/image identity,
trial budgets and reported costs are retained. Decoding was replayed with the
identified final decoder; capture-time status/gaps are also retained so the
excluded pilot and numbered-read improvement remain auditable.

Reported total cost is **$1.1931952**, including the excluded pilot. One timed-out
trial lacks final cost telemetry, so this is a lower bound, not a complete bill.
That trial had a $0.30 CLI budget. The user's authorization was $5 total; no
further live runs are included or inferred. In-flight responses can slightly
exceed the CLI's per-trial threshold (the compilation case demonstrates this).

Read a trace without making any model calls:

```bash
python -m gzip -d -c evals/baselines/native-2026-09-13/before-bounded-discovery.events.json.gz
```

The access token used for authentication is not included in the evidence.
