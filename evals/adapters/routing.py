"""Provider-specific discovery surfaces and conservative raw-event decoding.

These decoders never treat prose about using a skill as activation evidence.
Read evidence and successful native skill invocations remain distinct.
"""

from __future__ import annotations

import shlex
import re
import json
import os
from pathlib import Path
from pathlib import PurePosixPath


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(item["text"] for item in value if isinstance(item, dict) and isinstance(item.get("text"), str))
    return ""


def _path(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute():
        path = PurePosixPath("/workspace") / path
    # Do not resolve an agent path against the harness's filesystem.
    parts = []
    for part in path.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in {"/", "."}:
            parts.append(part)
    return "/" + "/".join(parts)


def _observation(path, inventory, event_index, kind, output=None):
    record = inventory.get(_path(path))
    if record is None:
        return None
    data = record["text"]
    # Bytes are verified only when the full source text is visible in the
    # tool output. File size alone is not evidence that the file was loaded.
    visible = output is not None and data.strip() and data.strip() in output
    return {
        "skill": record["skill"], "path": record["relative"], "kind": kind,
        "entrypoint": record["relative"] == "SKILL.md",
        "event_index": event_index,
        "verified_text_bytes": len(data.encode("utf-8")) if visible else None,
    }


def claude_events(events, inventory):
    calls = {}
    observations = []
    gaps = []
    completed = False
    for index, event in enumerate(events):
        if event.get("type") == "result":
            completed = event.get("subtype") == "success" and not event.get("is_error", False)
        message = event.get("message") or {}
        content = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block.get("id")] = (block.get("name"), block.get("input") or {})
            if block.get("type") != "tool_result":
                continue
            call = calls.pop(block.get("tool_use_id"), None)
            if call is None:
                gaps.append("unmatched_tool_result")
                continue
            name, arguments = call
            if not isinstance(arguments, dict):
                gaps.append("invalid_tool_arguments")
                continue
            if block.get("is_error"):
                continue
            observation = None
            if name == "Skill":
                skill = arguments.get("skill")
                entries = [(p, r) for p, r in inventory.items() if r["skill"] == skill and r["relative"] == "SKILL.md"]
                if len(entries) == 1:
                    observation = _observation(entries[0][0], inventory, index, "activation", _text(block.get("content")))
                else:
                    if isinstance(skill, str) and skill:
                        observations.append({
                            "skill": skill, "path": "SKILL.md", "kind": "activation",
                            "entrypoint": True, "event_index": index, "verified_text_bytes": None,
                        })
                    else:
                        gaps.append("unmapped_skill_invocation")
            elif name == "Read" and isinstance(arguments.get("file_path"), str):
                output = _text(block.get("content"))
                # The CLI prefixes Read output with line numbers. Strip only
                # that known decoration, then verify against source bytes.
                output = re.sub(r"(?m)^[ \t]*\d+(?:\t|→)", "", output)
                observation = _observation(arguments["file_path"], inventory, index, "read", output)
            elif name not in NON_READ_TOOLS:
                # Bash, Grep, nested agents and future tools can load text
                # through paths this decoder cannot attest.
                gaps.append("unobserved_read_surface:" + str(name))
            if observation:
                observations.append(observation)
    if calls:
        gaps.append("missing_tool_results")
    if not completed:
        gaps.append("incomplete_run")
    return observations, sorted(set(gaps))


def codex_events(events, inventory):
    observations = []
    # exec JSONL does not expose every possible skill activation/file read.
    # Even a successful cat is only read evidence, never a native activation.
    gaps = ["exec_stream_has_partial_read_telemetry"]
    for index, event in enumerate(events):
        item = event.get("item") or {}
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if item.get("type") != "command_execution" or item.get("exit_code") != 0:
            continue
        try:
            command = shlex.split(item.get("command", ""))
            if len(command) == 3 and command[0].rsplit("/", 1)[-1] in {"bash", "sh"} and command[1] in {"-c", "-lc"}:
                command = shlex.split(command[2])
        except ValueError:
            continue
        if len(command) == 3 and command[1] == "--":
            command.pop(1)
        if len(command) != 2 or command[0] not in {"cat", "/bin/cat", "/usr/bin/cat"} or command[1].startswith("-"):
            continue
        observation = _observation(command[1], inventory, index, "read", item.get("aggregated_output", ""))
        if observation:
            observations.append(observation)
    return observations, gaps


# Tools that cannot read a staged skill file: ToolSearch returns tool schemas
# and the web tools fetch only URLs. Every other tool leaves a telemetry gap.
NON_READ_TOOLS = frozenset({"Glob", "Write", "Edit", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch"})

# Web tools are granted so a trial can make the provider lookup the discovery
# guidance requires; without an allow rule, print mode refuses them. Bash stays
# unapproved here because the decoder cannot attest what it reads.
SURFACES = {
    "claude_code": {
        "directory": ".claude/skills", "credential": "ANTHROPIC_API_KEY", "executable": "claude",
        "command": ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits", "--permission-prompts", "none", "--allowedTools", "WebFetch,WebSearch", "--no-session-persistence", "--no-chrome", "--strict-mcp-config", "--setting-sources", "project", "--settings", '{"disableBundledSkills":true}'],
        "decode": claude_events,
    },
    "codex": {
        "directory": ".agents/skills", "credential": "OPENAI_API_KEY", "executable": "codex",
        "command": ["codex", "exec", "--json", "--ephemeral", "--sandbox", "workspace-write", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"],
        "decode": codex_events,
    },
}


def credentials(agent, credential_file=None):
    """Pass one explicitly selected credential to Docker, never host config.

    An optional Claude credentials file contributes only its OAuth access
    token. Neither the credential contents nor this returned environment are
    included in the evidence bundle.
    """
    name = SURFACES[agent]["credential"]
    environment = dict(os.environ)
    if agent == "claude_code":
        if credential_file is not None:
            try:
                token = json.loads(Path(credential_file).read_text())["claudeAiOauth"]["accessToken"]
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError("cannot load the explicitly selected Claude OAuth credential") from None
            if not isinstance(token, str) or not token:
                raise ValueError("Claude OAuth credential is empty")
            name = "CLAUDE_CODE_OAUTH_TOKEN"
            environment[name] = token
        elif not environment.get(name) and environment.get("CLAUDE_CODE_OAUTH_TOKEN"):
            name = "CLAUDE_CODE_OAUTH_TOKEN"
    return name, environment


def runtime_evidence(agent, events, requested_model, installed=("open-map-stack",)):
    versions = [e for e in events if e.get("type") == "oms.routing.runtime"]
    runtime = versions[0] if len(versions) == 1 else None
    gaps = []
    if not runtime or not runtime.get("version") or runtime.get("returncode"):
        gaps.append("runtime_identity_unavailable")
    result = {"runtime": runtime, "reported_cost_usd": None}
    if agent == "claude_code":
        from .claude_code import _claude_observability

        model, usage, cost, _, completed = _claude_observability(events, requested_model)
        startup = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
        result.update(discovered_skills=startup.get("skills"), resolved_model=model, usage=usage, reported_cost_usd=cost)
        if not set(installed) <= set(startup.get("skills") or []):
            gaps.append("controlled_skill_not_discovered")
        if not completed:
            gaps.append("incomplete_run")
    elif agent == "codex":
        from .codex import _codex_observability

        usage, _, completed = _codex_observability(events)
        result.update(resolved_model=None, requested_model=requested_model, usage=usage)
        if not completed:
            gaps.append("incomplete_run")
    return result, gaps


# The process has no host home/config mounts and inherits only these named
# credentials, never arbitrary host environment or image-defined agent flags.
# /root, /home and the admin scopes are fresh tmpfs mounts. No HOME/CODEX_HOME
# overrides are needed. CLIs must be globally installed in the clean image.
BOOTSTRAP = """import json, os, pathlib, pwd, subprocess, sys
payload=json.load(sys.stdin)
pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir).mkdir(parents=True,exist_ok=True)
if not all(os.access(path,os.R_OK) for path in payload['entrypoints']):
    print('controlled skill entrypoint is not readable',file=sys.stderr)
    sys.exit(2)
env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'}
credential=payload['credential']
if credential in os.environ:
    env[credential]=os.environ[credential]
if payload['command'][0]=='codex':
    login=subprocess.run(['codex','login','--with-api-key'], input=env.get(credential,''), text=True, capture_output=True, env=env)
    if login.returncode:
        print('routing authentication setup failed',file=sys.stderr)
        sys.exit(2)
version=subprocess.run([payload['command'][0],'--version'],capture_output=True,text=True,env=env)
print(json.dumps({'type':'oms.routing.runtime','version':version.stdout.strip(),'returncode':version.returncode}),flush=True)
sys.exit(subprocess.run(payload['command']+[payload['prompt']],env=env).returncode)
"""
