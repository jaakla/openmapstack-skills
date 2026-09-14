"""Native-discovery integration smoke tests, separate from project scoring.

Run through ``python evals/run.py routing --help``. A pinned, clean CLI image
is required for execution. No host credentials/configuration or repository
are mounted. Collection snapshot/arm migration remains issue #34.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from openmapstack.snapshot import create_skill_snapshot, inspect_skill_snapshot
from adapters.base import parse_json_lines
from adapters.routing import BOOTSTRAP, SURFACES, credentials, runtime_evidence

MATRIX = Path(__file__).parent / "routing-cases.yaml"
REPORT_SCHEMA = Path(__file__).parent / "schemas/routing-smoke-v1.schema.json"
# Freeze code identity when this runner starts, even if a developer edits the
# checkout while a long trial is executing.
HARNESS_HASHES = {
    name: "sha256:" + hashlib.sha256((REPO_ROOT / name).read_bytes()).hexdigest()
    for name in ("evals/routing.py", "evals/adapters/routing.py", "evals/adapters/claude_code.py", "evals/adapters/codex.py", "openmapstack/snapshot.py")
}


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_cases(path=MATRIX):
    matrix = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cases = matrix["cases"]
    ids = set()
    for case in cases:
        if not re.fullmatch(r"[a-z0-9-]+", case["id"]) or case["id"] in ids:
            raise ValueError("invalid or duplicate routing case id")
        ids.add(case["id"])
        if not case["prompt"].strip():
            raise ValueError("empty routing prompt")
        for profile, expected in case["expectations"].items():
            allowed = expected["support"] + ([expected["primary"]] if expected["primary"] else [])
            if set(allowed) & set(expected["forbidden"]):
                raise ValueError(f"contradictory routing expectation: {case['id']}/{profile}")
    return cases


def stage_skill(source, workspace, surface):
    """Stage a v1 single-skill snapshot in the native project discovery path."""
    text = (source / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    name = frontmatter["name"]
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("unsafe skill name")
    if name != "open-map-stack":
        raise ValueError("this increment supports the single open-map-stack snapshot; collection selection follows in #34")
    relative_root = Path(surface["directory"]) / name
    target = workspace / relative_root
    manifest = create_skill_snapshot(source, target)
    inventory = {}
    for entry in manifest["files"]:
        path = target / entry["path"]
        if path.suffix.lower() != ".md":
            continue
        inventory["/workspace/" + (relative_root / entry["path"]).as_posix()] = {
            "skill": name, "relative": entry["path"], "text": path.read_text(encoding="utf-8"),
        }
    return target, manifest, inventory


def grade_evidence(observations, gaps, expected):
    """Score observed selection only; never infer semantic primary ownership."""
    consumed = sorted({o["skill"] for o in observations if o["entrypoint"]})
    allowed = set(expected["support"])
    if expected["primary"]:
        allowed.add(expected["primary"])
    unexpected = sorted(set(consumed) - allowed)
    missing = expected["primary"] is not None and expected["primary"] not in consumed
    status = "failed" if unexpected else "not_testable" if gaps else "failed" if missing else "passed"
    verified = {(o["skill"], o["path"]): o["verified_text_bytes"] for o in observations if o["verified_text_bytes"] is not None}
    return {
        "status": status,
        "observed_skills": consumed,
        "unexpected_skills": unexpected,
        "required_skill_observed": not missing,
        "false_activation_count": len({o["skill"] for o in observations if o["kind"] == "activation" and o["skill"] not in allowed}),
        "false_activation_count_is_lower_bound": bool(gaps),
        "unexpected_consumption_count": len(unexpected),
        "verified_unique_text_bytes": sum(verified.values()),
        "text_bytes_complete": not gaps and all(o["verified_text_bytes"] is not None for o in observations),
        "telemetry_gaps": gaps,
        "primary_role": {"status": "not_testable", "reason": "tool events establish consumption, not semantic ownership"},
        "task_success": {"status": "not_testable", "reason": "routing smoke does not grade analytical outcomes; use paired project evals"},
    }



def container_command(image, workspace, credential, name):
    if not re.fullmatch(r"(?:[A-Za-z0-9._/:+-]+@)?sha256:[0-9a-f]{64}", image):
        raise ValueError("routing image must be pinned by sha256 digest or local image ID")
    if "," in str(workspace):
        raise ValueError("container mount path cannot contain a comma")
    return [
        "docker", "run", "--rm", "--pull=never", "--name", name,
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--user", f"{os.getuid()}:{os.getgid()}", "--workdir", "/workspace",
        "--tmpfs", "/tmp:rw,nosuid,size=512m", "--tmpfs", "/root:rw,nosuid,mode=1777,size=512m",
        "--tmpfs", "/home:rw,nosuid,mode=1777,size=64m", "--tmpfs", "/etc/codex:rw,nosuid,size=1m",
        "--tmpfs", "/etc/claude-code:rw,nosuid,size=1m",
        "--mount", f"type=bind,src={workspace},dst=/workspace",
        "--env", credential, "--entrypoint", "python3", "-i", image, "-c", BOOTSTRAP,
    ]


def run_trial(case, *, source, agent, model, image, destination, timeout=900, max_budget_usd=None, credential_file=None):
    destination.mkdir(parents=True, exist_ok=False)
    prompt = case["prompt"]
    record = {
        "schema": "openmapstack-routing-smoke/v1", "case": case["id"], "mode": "native_discovery",
        "profile": "single", "agent": agent, "model": model, "image": image,
        "prompt_sha256": sha256(prompt.encode()), "case_sha256": sha256(json.dumps(case, sort_keys=True).encode()),
        "expectation": case["expectations"]["single"],
        "status": "not_testable", "reason": None,
        "max_budget_usd": max_budget_usd,
        "harness_files": HARNESS_HASHES,
        "fixtures": [],
    }
    (destination / "prompt.md").write_text(prompt, encoding="utf-8")
    surface = SURFACES.get(agent)
    try:
        credential, environment = credentials(agent, credential_file) if surface else (None, {})
    except ValueError as exc:
        record["reason"] = str(exc)
        credential, environment = None, {}
    if record["reason"]:
        pass
    elif surface is None:
        record["reason"] = "adapter_has_no_native_discovery"
    elif not model or not image:
        record["reason"] = "explicit_model_and_pinned_image_required"
    elif not environment.get(credential):
        record["reason"] = "credential_unavailable"
    elif agent == "claude_code" and (max_budget_usd is None or max_budget_usd <= 0):
        record["reason"] = "positive_trial_budget_required"
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="oms-routing-") as temporary:
                workspace = Path(temporary)
                target, manifest, inventory = stage_skill(source, workspace, surface)
                # Persist context outside the writable mount, including the hash
                # needed to detect changes to the staged copy during execution.
                record["snapshot"] = manifest
                (destination / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
                command = [*surface["command"], "--model", model]
                if agent == "claude_code":
                    command.extend(["--max-budget-usd", str(max_budget_usd)])
                name = "oms-routing-" + uuid.uuid4().hex
                invocation = container_command(image, workspace, credential, name)
                payload = {"command": command, "prompt": prompt, "credential": credential, "entrypoint": "/workspace/" + target.relative_to(workspace).as_posix() + "/SKILL.md"}
                try:
                    started = time.monotonic()
                    proc = subprocess.run(invocation, input=json.dumps(payload), text=True, capture_output=True, timeout=timeout, check=False, env=environment)
                    record["duration_s"] = time.monotonic() - started
                    # Tool output can echo an environment variable. Retain the
                    # event shape while redacting the forwarded credential value.
                    secret = environment[credential]
                    stdout = proc.stdout.replace(secret, "<REDACTED>")
                    stderr = proc.stderr.replace(secret, "<REDACTED>")
                    (destination / "stdout.jsonl").write_text(stdout, encoding="utf-8")
                    (destination / "stderr.txt").write_text(stderr, encoding="utf-8")
                    raw, unparsed = parse_json_lines(stdout)
                    (destination / "events.json").write_text(json.dumps(raw, indent=2) + "\n")
                    observations, gaps = surface["decode"](raw, inventory)
                    runtime, runtime_gaps = runtime_evidence(agent, raw, model)
                    record.update(runtime)
                    gaps.extend(runtime_gaps)
                    if unparsed:
                        gaps.append("unparsed_stdout")
                    if proc.returncode:
                        gaps.append("agent_or_container_failed")
                    inspection = inspect_skill_snapshot(target)
                    if not inspection["intact"] or inspection["recomputed_sha256"] != manifest["content_sha256"]:
                        gaps.append("controlled_skill_changed")
                    record["observations"] = observations
                    record["selection"] = grade_evidence(observations, sorted(set(gaps)), record["expectation"])
                    record["status"] = record["selection"]["status"]
                    if proc.returncode or set(gaps) & {"controlled_skill_changed", "controlled_skill_not_discovered"}:
                        record["status"] = "not_testable"
                    record["returncode"] = proc.returncode
                except subprocess.TimeoutExpired as exc:
                    # A killed docker client does not necessarily stop its container.
                    try:
                        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30, check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        record["cleanup_required"] = name
                    partial = exc.stdout or ""
                    if isinstance(partial, bytes):
                        partial = partial.decode("utf-8", errors="replace")
                    partial = partial.replace(environment[credential], "<REDACTED>")
                    (destination / "stdout.jsonl").write_text(partial, encoding="utf-8")
                    record["reason"] = "timeout"
                except (OSError, ValueError) as exc:
                    record["reason"] = f"{type(exc).__name__}: {exc}"
        except (OSError, ValueError, KeyError, IndexError) as exc:
            record["status"] = "not_testable"
            record["reason"] = f"preflight: {type(exc).__name__}: {exc}"
    Draft202012Validator(json.loads(REPORT_SCHEMA.read_text())).validate(record)
    (destination / "routing.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--case", action="append")
    parser.add_argument("--agent", choices=[*SURFACES, "openai_compatible"])
    parser.add_argument("--model")
    parser.add_argument("--image", help="locally available, clean CLI image pinned by digest; never pulled automatically")
    parser.add_argument("--skill-source", type=Path, default=REPO_ROOT / "skills/open-map-stack")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--max-budget-usd", type=float, help="total budget divided across the selected Claude trials; leave headroom for an in-flight response")
    parser.add_argument("--credential-file", type=Path, help="explicit Claude OAuth credentials file; only its access token is passed, never persisted")
    args = parser.parse_args(argv)
    cases = load_cases()
    if args.list:
        for case in cases:
            print(case["id"])
        return 0
    if not args.agent or not args.out or not args.case:
        parser.error("execution requires --agent, --out and explicit --case selection")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    known = {c["id"] for c in cases}
    if not set(args.case) <= known:
        parser.error("unknown routing case")
    if args.max_budget_usd is not None and (not 0 < args.max_budget_usd < float("inf") or args.agent != "claude_code"):
        parser.error("a finite positive --max-budget-usd is supported for claude_code only")
    selected = [c for c in cases if c["id"] in args.case]
    trial_budget = float((Decimal(str(args.max_budget_usd)) / len(selected)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)) if args.max_budget_usd else None
    results = []
    spent = 0.0
    for case in selected:
        result = run_trial(case, source=args.skill_source.resolve(), agent=args.agent, model=args.model, image=args.image, destination=args.out / case["id"], timeout=args.timeout, max_budget_usd=trial_budget, credential_file=args.credential_file)
        results.append(result)
        cost = result.get("reported_cost_usd")
        if args.max_budget_usd:
            # Unknown spend or a failed runtime prevents further charged trials.
            if not isinstance(cost, (int, float)) or isinstance(cost, bool) or not 0 <= cost < float("inf"):
                break
            spent += cost
            if result.get("returncode") != 0:
                break
            if spent + trial_budget > args.max_budget_usd:
                break
    unrun = [c["id"] for c in selected if c["id"] not in {r["case"] for r in results}]
    summary = {"schema": "openmapstack-routing-smoke-summary/v1", "results": results, "unrun_cases": unrun, "reported_cost_usd": spent if args.max_budget_usd else None}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    for result in results:
        print(f"{result['case']}: {result['status']}")
    return 2 if unrun or any(r["status"] == "not_testable" for r in results) else 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
