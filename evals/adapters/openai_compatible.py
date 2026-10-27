"""OpenAI-compatible chat-completions adapter for live evals.

Drives any OpenAI-compatible `/chat/completions` endpoint (OpenRouter,
vLLM, llama.cpp server, ...) as an autonomous coding agent through a
tool-execution loop: the model writes files and runs shell commands inside
the trial workspace until it produces a final message with no tool calls.
Shell commands run in the rootless Bubblewrap sandbox of ``isolation.py``:
only the workspace is writable, staged guidance is read-only, and the adapter
refuses to run where that sandbox is unavailable.

All configuration comes from the environment — no CLI install:

    OPENAI_COMPATIBLE_BASE_URL   API root, e.g. https://openrouter.ai/api/v1
    OPENAI_COMPATIBLE_API_KEY    bearer token (secret; never recorded)
    OPENAI_COMPATIBLE_MODEL      default model id (--model overrides it)

This module is only imported by `--mode live` runs, never by fixture CI.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .base import AgentAdapter, AgentRunResult, http_provider_failure
from .isolation import Sandbox, unavailable_reason

MAX_TURNS = 64
MAX_TOOL_OUTPUT_CHARS = 20_000
SHELL_TIMEOUT_S = 120
HTTP_TIMEOUT_S = 300

SYSTEM_PROMPT = """You are an autonomous coding agent working inside a plain \
directory (your workspace). Complete the user's task there. You can run \
shell commands, create, read, and list files, read large files in line ranges, \
and make exact-string edits instead of rewriting whole files. \
Read controlled guidance when provided; write files only in your workspace. \
Work incrementally: inspect the workspace, write the needed files, run and \
verify your work, and iterate until the task is done. When you are finished, \
reply with a short summary and no tool calls."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": ("Run a shell command in a sandbox at the workspace and return its combined output and exit "
                                "status. Only the workspace is writable; guidance is read-only."),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a workspace-relative text file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative destination path."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file in the workspace or the runner-provided read-only guidance directory. Output is capped "
                f"at {MAX_TOOL_OUTPUT_CHARS} characters of file content. A partial read starts with a one-line note giving "
                "the line range, the file's total lines and characters, and the offset to continue from; the "
                "content after it is exact."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace; controlled guidance may be beside it."},
                    "offset": {"type": "integer", "description": "First line to read, 1-based (default 1)."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read (default: as many as fit)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact string in an existing workspace text file. old_string must match the file "
                "exactly, including whitespace, and be unique unless replace_all is true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "old_string": {"type": "string", "description": "Exact text to replace."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)."},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List a directory in the workspace or the runner-provided read-only guidance directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative directory (default '.')."},
                },
            },
        },
    },
]


def _truncate(value: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} characters]"


def _resolve_tool_path(workspace: Path, raw: Any, guidance: Path | None, *, write: bool = False) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path must be a non-empty workspace-relative string")
    resolved_workspace = workspace.resolve()
    lexical_path = Path(os.path.abspath(resolved_workspace / raw))
    candidate = lexical_path.resolve()
    # Check both spellings: a workspace link cannot grant guidance writes,
    # nor can a link inside guidance redirect a write back to the workspace.
    if guidance is not None:
        if write and (lexical_path.is_relative_to(guidance) or candidate.is_relative_to(guidance)):
            raise ValueError("controlled guidance directory is read-only")
        if not write and candidate.is_relative_to(guidance):
            return candidate
    if candidate.is_relative_to(resolved_workspace):
        return candidate
    raise ValueError(f"path escapes the workspace or controlled guidance: {raw!r}")


def _positive_int(args: dict[str, Any], key: str) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key!r} must be a positive integer, got {value!r}")
    return value


def _lines(text: str) -> list[str]:
    """Lines ending at ``\\n`` only, as tracebacks, ``grep -n`` and ``sed`` count them."""
    return io.StringIO(text, newline="\n").readlines()


def _occurrences(text: str, old: str) -> int:
    """Occurrences of ``old`` in ``text``, overlapping ones included."""
    count, index = 0, text.find(old)
    while index != -1:
        count += 1
        index = text.find(old, index + 1)
    return count


def _crlf(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\n", "\r\n")


def _read_range(text: str, offset: int | None, limit: int | None) -> tuple[bool, str]:
    """Whole lines from ``offset``, within ``limit`` and the output cap."""
    lines = _lines(text)
    start = (offset or 1) - 1
    if start and start >= len(lines):
        return False, f"offset {start + 1} is past the end of the file ({len(lines)} lines)"
    if not lines:
        return True, "" if offset is None and limit is None else "[read_file: empty file]"
    end = len(lines) if limit is None else min(len(lines), start + limit)
    chosen, size = [], 0
    for line in lines[start:end]:
        if chosen and size + len(line) > MAX_TOOL_OUTPUT_CHARS:
            break
        chosen.append(line)
        size += len(line)
    stop = start + len(chosen)
    content = "".join(chosen)
    clipped = len(content) > MAX_TOOL_OUTPUT_CHARS
    if offset is None and limit is None and stop == len(lines) and not clipped:
        return True, content
    note = f"[read_file: lines {start + 1}-{stop} of {len(lines)}; {len(text)} characters total; "
    if clipped:
        content = content[:MAX_TOOL_OUTPUT_CHARS]
        note += f"line {stop} was cut at {MAX_TOOL_OUTPUT_CHARS} characters; "
    note += f"more remains, continue with offset={stop + 1}]" if stop < len(lines) else "end of file]"
    # The note leads, so the content after it is exactly what the file holds.
    return True, note + "\n" + content


def _tool_arguments(raw: Any, finish_reason: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    diagnostic: dict[str, Any] = {
        "code": "tool_arguments_truncated" if finish_reason == "length" else "tool_arguments_malformed",
        "message": ("Response reached its output limit; invalid tool arguments were not executed."
                    if finish_reason == "length" else
                    "Tool arguments must be a JSON object; invalid arguments were not executed."),
        "finish_reason": finish_reason,
        "argument_type": type(raw).__name__,
    }
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        diagnostic["parse_error"] = {"message": exc.msg, "position": exc.pos,
                                     "line": exc.lineno, "column": exc.colno}
    else:
        if isinstance(parsed, dict):
            return parsed, None
        diagnostic["parsed_type"] = type(parsed).__name__
    return None, diagnostic


class OpenaiCompatibleAdapter(AgentAdapter):
    """Agent adapter for any OpenAI-compatible chat-completions endpoint.

    The class name follows the eval runner's adapter-loading convention
    (`openai_compatible` -> `OpenaiCompatibleAdapter`).
    """

    name = "openai_compatible"
    executable = ""  # no CLI; availability is environment-based

    @staticmethod
    def _env() -> dict[str, str | None]:
        return {
            "base_url": (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip().rstrip("/") or None,
            "api_key": (os.environ.get("OPENAI_COMPATIBLE_API_KEY") or "").strip() or None,
            "model": (os.environ.get("OPENAI_COMPATIBLE_MODEL") or "").strip() or None,
        }

    def is_available(self) -> bool:
        env = self._env()
        return bool(env["base_url"] and env["api_key"] and env["model"])

    def _post_chat(self, base_url: str, api_key: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def _guidance_root(self, workspace: Path) -> Path | None:
        if self.trial_root is None:
            return None
        trial = self.trial_root.resolve()
        if not workspace.resolve().is_relative_to(trial):
            return None
        guidance = trial / "benchmark-context" / "openmapstack"
        # Keep the lexical boundary: the resolver follows links before
        # allowing reads, and rejects writes through either spelling.
        return guidance if guidance.is_dir() else None

    def _shell_sandbox(self, workspace: Path) -> Sandbox:
        sandbox = Sandbox.for_python_agent(workspace, {})
        guidance = self._guidance_root(workspace)
        # A redirected guidance link is not an allowance to mount its target.
        if guidance is not None and guidance.resolve() == guidance:
            sandbox.read_only.append(guidance)
        return sandbox

    def _execute_tool(self, name: str, args: Any, workspace: Path, remaining_s: float) -> tuple[bool, str]:
        if not isinstance(args, dict):
            return False, f"tool {name!r} arguments must be an object, got {type(args).__name__}"
        try:
            if name == "run_shell":
                command = args.get("command")
                if not isinstance(command, str) or not command.strip():
                    return False, "run_shell requires a non-empty 'command' string"
                # Never fall back to the host: the model authors this command.
                reason = unavailable_reason()
                if reason:
                    return False, f"refusing an unisolated shell command: {reason}"
                sandbox = self._shell_sandbox(workspace)
                proc = subprocess.run(
                    [*sandbox.argv(workspace), "/bin/sh", "-c", command],
                    env=sandbox.environment({}),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=max(1, min(SHELL_TIMEOUT_S, remaining_s)),
                    check=False,
                )
                output = f"exit={proc.returncode}\n{proc.stdout}{proc.stderr}".strip()
                return proc.returncode == 0, _truncate(output)
            if name == "write_file":
                target = _resolve_tool_path(workspace, args.get("path"), self._guidance_root(workspace), write=True)
                content = args.get("content")
                if not isinstance(content, str):
                    return False, "write_file requires 'content' to be a string"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return True, f"wrote {len(content)} chars to {target.relative_to(workspace.resolve())}"
            if name == "read_file":
                target = _resolve_tool_path(workspace, args.get("path"), self._guidance_root(workspace))
                if not target.is_file():
                    return False, f"not a file: {args.get('path')!r}"
                offset, limit = _positive_int(args, "offset"), _positive_int(args, "limit")
                with target.open(encoding="utf-8", errors="replace", newline="") as handle:
                    return _read_range(handle.read(), offset, limit)
            if name == "edit_file":
                target = _resolve_tool_path(workspace, args.get("path"), self._guidance_root(workspace), write=True)
                old, new = args.get("old_string"), args.get("new_string")
                if not isinstance(old, str) or not old or not isinstance(new, str):
                    return False, "edit_file requires a non-empty 'old_string' and a string 'new_string'"
                if old == new:
                    return False, "old_string and new_string are identical; nothing to change"
                replace_all = args.get("replace_all", False)
                if not isinstance(replace_all, bool):
                    return False, "edit_file 'replace_all' must be a boolean"
                if not target.is_file():
                    return False, f"not a file: {args.get('path')!r}"
                # Keep line endings as written; a read_file excerpt matches them.
                with target.open(encoding="utf-8", newline="") as handle:
                    text = handle.read()
                matched_crlf = False
                if old not in text and "\n" in old and "\r\n" in text and _crlf(old) in text:
                    old, new, matched_crlf = _crlf(old), _crlf(new), True
                count = _occurrences(text, old)
                if count == 0:
                    hint = " The file uses CRLF (\\r\\n) line endings." if "\n" in old and "\r\n" in text else ""
                    return False, (f"old_string not found in {args.get('path')!r}; "
                                   f"read the file and copy the text exactly.{hint}")
                if count > 1 and not replace_all:
                    return False, (f"old_string occurs {count} times in {args.get('path')!r}; "
                                   "include more surrounding text to make it unique, or set replace_all")
                replaced = text.count(old) if replace_all else 1
                text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
                with target.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(text)
                return True, (f"replaced {replaced} occurrence{'s' if replaced > 1 else ''} in "
                              f"{target.relative_to(workspace.resolve())}"
                              f"{' using its CRLF line endings' if matched_crlf else ''}; "
                              f"file now has {len(_lines(text))} lines")
            if name == "list_dir":
                target = _resolve_tool_path(workspace, args.get("path") or ".", self._guidance_root(workspace))
                if not target.is_dir():
                    return False, f"not a directory: {args.get('path')!r}"
                entries = []
                for entry in sorted(target.iterdir()):
                    entries.append(entry.name + ("/" if entry.is_dir() else ""))
                return True, _truncate("\n".join(entries))
            return False, f"unknown tool: {name!r}"
        except subprocess.TimeoutExpired:
            return False, f"command timed out after {min(SHELL_TIMEOUT_S, remaining_s):.0f}s"
        except Exception as exc:  # noqa: BLE001 - tool failures are reported to the model
            return False, f"{type(exc).__name__}: {exc}"

    def run(
        self,
        prompt: str,
        workspace: Path,
        fixture: Path | None = None,
        timeout_s: int = 900,
        model: str | None = None,
        seed: int | None = None,
    ) -> AgentRunResult:
        env = self._env()
        base_url, api_key, env_model = env["base_url"], env["api_key"], env["model"]
        requested_model = model or env_model
        missing = [
            name
            for name, value in (
                ("OPENAI_COMPATIBLE_BASE_URL", base_url),
                ("OPENAI_COMPATIBLE_API_KEY", api_key),
                ("OPENAI_COMPATIBLE_MODEL (or --model)", requested_model),
            )
            if not value
        ]
        isolation_unavailable = None if missing else unavailable_reason()

        if missing or isolation_unavailable:
            return AgentRunResult(
                agent=self.name,
                model=requested_model,
                workspace=workspace,
                duration_s=0.0,
                success=False,
                returncode=None,
                command=["POST", "<OPENAI_COMPATIBLE_BASE_URL>/chat/completions", "<PROMPT:prompt.md>"],
                stderr=(f"OpenAI-compatible adapter is missing required configuration: {', '.join(missing)}" if missing
                        else f"refusing an unisolated live run: {isolation_unavailable}"),
                permissions={"sandbox": "workspace-write", "network": True, "session_persistence": False},
                metadata={
                    "requested_seed": seed,
                    "adapter_not_started": True,
                    "missing_environment": missing,
                    "isolation_unavailable": isolation_unavailable,
                },
            )

        assert base_url is not None and api_key is not None and requested_model is not None
        if fixture is not None and fixture.exists():
            shutil.copytree(fixture, workspace, dirs_exist_ok=True)

        start = time.monotonic()
        deadline = start + timeout_s
        recorded_command = ["POST", f"{base_url}/chat/completions", "<PROMPT:prompt.md>"]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        events: list[dict[str, Any]] = []
        finish_reasons: list[Any] = []
        tool_call_diagnostics: list[dict[str, Any]] = []
        usage: dict[str, float | int] = {}
        cost_usd: float | None = None
        models_observed: set[str] = set()
        completed = False
        timed_out = False
        final_message: str | None = None
        error_text: str | None = None
        failure = None
        turns = 0

        while turns < MAX_TURNS:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                error_text = f"timed out after {timeout_s}s"
                break
            payload = {
                "model": requested_model,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
            }
            try:
                response = self._post_chat(base_url, api_key, payload, timeout_s=min(remaining, HTTP_TIMEOUT_S))
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001 - diagnostic best effort
                    pass
                error_text = f"HTTP {exc.code} from {base_url}/chat/completions: {_truncate(body, 2000) or exc.reason}"
                error_text = error_text.replace(api_key, "<REDACTED>")
                failure = http_provider_failure(exc.code, error_text)
                break
            except Exception as exc:  # noqa: BLE001 - transport errors end the run
                error_text = f"{type(exc).__name__}: {exc}"
                break

            turns += 1
            raw_usage = response.get("usage")
            if isinstance(raw_usage, dict):
                has_split = all(isinstance(raw_usage.get(key), (int, float)) and not isinstance(raw_usage.get(key), bool) for key in ("prompt_tokens", "completion_tokens"))
                for key in ("prompt_tokens", "completion_tokens"):
                    value = raw_usage.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        usage[key] = usage.get(key, 0) + value
                total = raw_usage.get("total_tokens")
                if not has_split and isinstance(total, (int, float)) and not isinstance(total, bool):
                    usage["total_tokens"] = usage.get("total_tokens", 0) + total
                provider_cost = raw_usage.get("cost")
                if isinstance(provider_cost, (int, float)) and not isinstance(provider_cost, bool):
                    cost_usd = (cost_usd or 0.0) + float(provider_cost)
            if isinstance(response.get("model"), str):
                models_observed.add(response["model"])

            choices = response.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
            finish_reason = choice.get("finish_reason")
            finish_reasons.append(finish_reason)
            message = choice.get("message")
            if not isinstance(message, dict):
                error_text = "response contained no assistant message"
                break

            content = message.get("content")
            tool_calls = message.get("tool_calls") or []
            assistant_entry: dict[str, Any] = {"role": "assistant", "content": content if isinstance(content, str) else ""}
            if tool_calls:
                assistant_entry["tool_calls"] = tool_calls
            messages.append(assistant_entry)
            events.append(
                {
                    "type": "assistant.message",
                    "turn": turns,
                    "finish_reason": finish_reason,
                    "content": _truncate(assistant_entry["content"], 2000),
                    "tool_calls": [
                        {
                            "id": call.get("id"),
                            "name": (call.get("function") or {}).get("name") if isinstance(call, dict) else None,
                            "arguments": (call.get("function") or {}).get("arguments") if isinstance(call, dict) else None,
                        }
                        for call in tool_calls
                        if isinstance(call, dict)
                    ],
                }
            )

            if not tool_calls:
                if finish_reason == "length":
                    error_text = "response truncated at the output limit (finish_reason=length); no completed final message"
                    break
                completed = True
                final_message = assistant_entry["content"] or None
                break

            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                name = function.get("name")
                raw_arguments = function.get("arguments")
                args, diagnostic = _tool_arguments(raw_arguments, finish_reason)
                if diagnostic is not None:
                    diagnostic.update(turn=turns, tool=name, tool_call_id=call.get("id"))
                    tool_call_diagnostics.append(diagnostic)
                    ok, output = False, json.dumps(diagnostic)
                else:
                    ok, output = self._execute_tool(name, args, workspace, deadline - time.monotonic())
                tool_result = {"type": "tool.result", "turn": turns, "tool": name,
                               "ok": ok, "output": _truncate(output, 2000)}
                if diagnostic is not None:
                    tool_result["diagnostic"] = diagnostic
                events.append(tool_result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or f"call_{turns}_{len(messages)}",
                        "content": output,
                    }
                )
        else:
            error_text = f"exceeded {MAX_TURNS} model turns without a final message"

        duration = time.monotonic() - start
        if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        success = completed and not timed_out and error_text is None and bool(requested_model)
        stderr_parts = [part for part in (error_text, "no final message received" if timed_out and not error_text else None) if part]

        return AgentRunResult(
            agent=self.name,
            model=requested_model,
            workspace=workspace,
            duration_s=duration,
            success=success,
            returncode=0 if completed else None,
            command=recorded_command,
            stdout="",
            stderr="\n".join(stderr_parts),
            version=None,
            events=events,
            usage=usage,
            cost_usd=cost_usd,
            final_message=final_message,
            failure=failure,
            permissions={
                "sandbox": "workspace-write",
                "network": True,
                "session_persistence": False,
                "isolation": self._shell_sandbox(workspace).evidence(),
            },
            metadata={
                "base_url": base_url,
                "requested_model": requested_model,
                "models_observed": sorted(models_observed),
                "model_source": "requested" if model else "env:OPENAI_COMPATIBLE_MODEL",
                "requested_seed": seed,
                "timed_out": timed_out,
                "timeout_s": timeout_s,
                "turns": turns,
                "finish_reasons": finish_reasons,
                "tool_call_diagnostics": tool_call_diagnostics,
                "max_turns": MAX_TURNS,
                "structured_completion": completed,
                "cost_available": cost_usd is not None,
                "cost_is_estimate": False,
                "api_key_source": "env:OPENAI_COMPATIBLE_API_KEY",
            },
        )
