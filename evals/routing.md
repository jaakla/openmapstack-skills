# Native skill-discovery smoke tests

Issue #32 adds an isolated discovery path alongside the existing explicitly
injected `plain`/`oms` project evals. It does not reinterpret those v1 arms.
OpenMapBench still owns public benchmark orchestration; this path is a small
integration test for the installed skill surface and its event evidence.

`routing-cases.yaml` is the routing matrix: unhinted task prompts, a required
primary skill, permitted supporting skills and forbidden activation. It covers
bounded discovery, chosen-engine SQL, existing-analysis compilation, ambiguous
architecture, billion-row and future-scale architecture, casual place lookup,
and material analysis with the generalist installed alone. The matrix also
records four-skill expectations. `--profile single` retains the historical v1
single-skill payload and report. `--profile collection` stages complete v2
payloads and emits `openmapstack-routing-smoke/v2`; repeat `--skill NAME` to
select a subset, including a standalone specialist. Source defaults follow the
profile. These are final-state selection checks, not equivalence comparisons.

## Isolation and execution

```bash
python evals/run.py routing --list
python evals/run.py routing --agent claude_code --model EXACT_MODEL_ID \
  --image sha256:EXACT_LOCAL_IMAGE_ID \
  --skill-source /path/to/controlled/source \
  --case chosen-engine-sql --case casual-place-lookup \
  --max-budget-usd 1 --out /tmp/oms-routing-evidence
```

Execution requires an explicit case selection and a locally available image
pinned by digest. `containers/routing.Dockerfile` builds a runtime from a pinned
Node image and exact CLI versions supplied as build arguments. Do not include
the repository, user homes, plugins, credentials or policy/customization files
in that image. A clean image with globally installed Python 3 and a native CLI
is also supported; record its digest and build recipe. The image must have a
passwd entry for the invoking user's numeric UID (the stock Node and Ubuntu
images provide UID 1000). The container uses that UID to read/write the bind
mount without elevated filesystem capabilities. Images are not pulled
automatically.

The only host mount is a fresh trial directory containing the controlled
skill snapshot (v1 single or v2 collection). Expected answers, the harness and the uncontrolled repository remain
outside the mount. Root/home and admin configuration directories are empty
tmpfs mounts; the image filesystem is read-only. The agent process receives a
fixed minimal environment and one named credential. This avoids changing host
configuration or depending on sandbox flags that restrict writes but still
permit reads of the user's installed skills.

Provider-specific surfaces live in `adapters/routing.py`:

- Claude discovers `.claude/skills/<name>` with project settings,
  a request to disable bundled skills, strict MCP configuration and **without safe mode**
  (safe mode disables skills). Use `ANTHROPIC_API_KEY`, an existing
  `CLAUDE_CODE_OAUTH_TOKEN`, or explicitly pass `--credential-file` pointing to
  a Claude OAuth credential file. Only the access token is forwarded; the file
  and other host settings are never mounted.
  Startup discovery must include the controlled skill before selection is
  graded. Some CLI built-ins remain visible even when bundled skills are
  disabled; the actual startup inventory is retained as evidence.
- Codex discovers `.agents/skills/<name>`, ignores user config/rules,
  and uses a fresh container login from `OPENAI_API_KEY`. Its JSONL decoder
  conservatively reports partial read telemetry, so a matching observed read
  alone cannot produce a complete routing pass.
- `openai_compatible` has no native discovery implementation and returns
  `not_testable` without making an API call.

Discovery locations were checked against the installed CLI help and official
[Claude skill documentation](https://code.claude.com/docs/en/skills) and
[Codex skill documentation](https://learn.chatgpt.com/docs/build-skills).

For Claude, `--max-budget-usd` is required and divided over selected trials.
It is passed to each CLI invocation. Leave headroom below the authorized cap
for an in-flight response. Unknown cost or an unsuccessful process prevents
further charged trials. A timeout stops the named container and retains partial
stdout. No new paid runs should be inferred from fixture/test commands.

## Evidence and interpretation

Every trial saves the unchanged prompt, prompt/case hashes, snapshot inventory,
runtime identity, harness file hashes, raw event stream, decoded observations
and selection result. The forwarded credential is redacted if it appears in
captured output. These prompt-only smoke cases have an explicit empty fixture list.
Observations refer to zero-based entries in `events.json` and distinguish a
successful native `Skill` invocation from a file read. Prose claims, failed
tool calls, mere path mentions and missing completions are not positive evidence.

Selection checks required and unexpected skill consumption. It does **not**
prove semantic primary ownership or analytical task success; both remain
explicitly unscored. Use the [final-state acceptance checklist](final-state-acceptance.md) to assess
task quality separately from routing. Historical runs are context only.

Verified unique text bytes count source text actually visible in tool output,
deduplicated by skill/path. They are a lower bound when a response is truncated,
decorated, absent or otherwise unverifiable. Snapshot bytes describe the
available payload, not bytes actually loaded. Native false-activation counts
exclude inferred reads; unexpected consumption is reported separately.

Missing telemetry, unsupported discovery, runtime failures and changed controlled
skill files remain `not_testable` with exit 2. Observed forbidden consumption
can establish failure even with partial telemetry. A negative case cannot pass
merely because an adapter supplied no usable event stream. Exit 1 denotes a
selection failure; exit 0 denotes observed selection success only.

## Final collection selection

Use the same explicit model/image/budget arguments above and add
`--profile collection`. For example, `--case chosen-engine-sql --skill spatial-sql`
checks a standalone install; omitting `--skill` installs all four. A subset still
uses the case's collection expectations, so include its expected owner.
The runner verifies discovery of every controlled skill, retains the selected
v2 inventory, and detects edits to any controlled payload file. Runtime settings
created beside the skills are outside the payload's integrity boundary.
Neither case expectations nor skill-reading instructions are sent to the agent.

No new paid execution is implied by these commands. Final acceptance scope and
remaining budget are still pending under #39.
