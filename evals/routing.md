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
records the planned four-skill expectations. This increment runs **only the
single `open-map-stack` snapshot**; #34 owns collection snapshots and versioned
arm integration before collection comparisons can run.

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

The only host mount is a fresh trial directory containing a controlled v1
snapshot. Expected answers, the harness and the uncontrolled repository remain
outside the mount. Root/home and admin configuration directories are empty
tmpfs mounts; the image filesystem is read-only. The agent process receives a
fixed minimal environment and one named credential. This avoids changing host
configuration or depending on sandbox flags that restrict writes but still
permit reads of the user's installed skills.

Provider-specific surfaces live in `adapters/routing.py`:

- Claude discovers `.claude/skills/open-map-stack` with project settings,
  a request to disable bundled skills, strict MCP configuration and **without safe mode**
  (safe mode disables skills). Use `ANTHROPIC_API_KEY`, an existing
  `CLAUDE_CODE_OAUTH_TOKEN`, or explicitly pass `--credential-file` pointing to
  a Claude OAuth credential file. Only the access token is forwarded; the file
  and other host settings are never mounted.
  Startup discovery must include the controlled skill before selection is
  graded. Some CLI built-ins remain visible even when bundled skills are
  disabled; the actual startup inventory is retained as evidence.
- Codex discovers `.agents/skills/open-map-stack`, ignores user config/rules,
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
explicitly unscored. Use the existing paired project evals to assess task
quality, and retain this distinction when the collection contract is added.

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
