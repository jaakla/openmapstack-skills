# Baseline before the 0.4.0 refactor

These are intentional, compact evidence artifacts for issue #32. They freeze
the release and pre-refactor main separately; neither is a native-routing pass.

| Revision | Contract fixtures | Mutation detection | Limitations |
|---|---:|---:|---|
| `v0.3.0` / `d4e1bd3cc6f35049e2cbbd6813a3d10787b6bcfe` | 15/15 | 25/25 | Two contract assertions not testable; two unmet soft gates |
| pre-refactor / `a9cf23d302761275ddc8d6dbdb3e60cab5100a03` | 16/16 | 26/26 | Two contract assertions not testable; two unmet soft gates |

Each JSON records the skill's v1 content hash and per-file inventory, entry-point
size, runtime, fixture outcomes and missing capabilities. The project-contract
section hash guards the lossless guidance move in #33. The fixture captures
used Python 3.12.3 and DuckDB 1.5.5; richer environments can exercise additional
capabilities, so compare capability counts as well as pass rates.

The [historical live run](https://github.com/jaakla/openmapstack-skills/actions/runs/34096158032)
used Claude Code 2.1.263 and `claude-sonnet-4-6` on the 0.3.0 revision with
explicit skill injection. It reported **0/15 graded trials passing and 15 setup
failures** over 30 trials. `v0.3.0-live.json` retains its arm provenance, summary
and per-trial outcomes. Its recorded skill hash matches this frozen release.
The workflow's successful conclusion is not a successful agent benchmark.
These results do not establish whether failures came from skill guidance,
adapter behavior, model limitations or runtime setup.

No historical paired arms or native-discovery evidence were found in that
artifact. No pre-refactor-main live artifact was found. These gaps are explicit;
the single skill has no meaningful four-way routing precision baseline.

## Reproduce and inspect

Export each exact revision into an empty directory **outside this repository**:

```bash
git archive d4e1bd3cc6f35049e2cbbd6813a3d10787b6bcfe -o /tmp/oms-release.tar
git archive a9cf23d302761275ddc8d6dbdb3e60cab5100a03 -o /tmp/oms-pre-refactor.tar
```

Extract each archive separately. Using an environment with
`evals/requirements.txt` installed, run the archived runner from that export:

```bash
python evals/run.py --mode fixture --json /tmp/fixture.json
python -m openmapstack skill-snapshot --out /tmp/skill-snapshot --json
```

Use a different empty snapshot destination for each revision. A git archive
has no `.git`, so its freshly generated snapshot cannot recover the revision;
the baseline's top-level `revision` identifies the archive instead. Compare
`content_sha256`, inventory and case outcomes, not timestamp-dependent hashes
of newly generated reports. Full-report hashes here identify the captured
reports; they are not expected to remain identical on rerun.

Retrieve the historical full audit bundle, while GitHub retains it:

```bash
gh run download 34096158032 --repo jaakla/openmapstack-skills \
  --name eval-benchmark-claude_code-34096158032 --dir /tmp/oms-historical-live
```

The artifact ID and SHA256 of its `eval-benchmark-results-claude_code.json` are
recorded in `v0.3.0-live.json`. The compact committed evidence remains readable
if the full GitHub artifact expires.
