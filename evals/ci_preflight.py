"""Offline configuration gate for the scheduled benchmark; never contacts a provider."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping

from evals.run import build_summary


REQUIRED = {
    "claude_code": ("ANTHROPIC_API_KEY",),
    "codex": ("OPENAI_API_KEY",),
    "openai_compatible": ("OPENAI_COMPATIBLE_BASE_URL", "OPENAI_COMPATIBLE_API_KEY"),
}


def check_configuration(agent: str, model: str, environment: Mapping[str, str], output: Path) -> bool:
    missing = [name for name in REQUIRED[agent] if not environment.get(name, "").strip()]
    if not model.strip():
        missing.append("exact benchmark model (workflow input or repository variable)")
    if not missing:
        return True
    # A run-level skip, with zero executed/graded/passed trials. The report
    # renders a skipped preflight record without inventing a case result.
    reason = f"{agent} is unconfigured; missing: {', '.join(missing)}"
    summary = build_summary([], {"mode": "live", "agent": agent, "model": model or None})
    summary.update(run_skipped=True, skip_reason=reason)
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"SKIPPED / NOT RUN: {reason}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=REQUIRED, required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    ready = check_configuration(args.agent, args.model, os.environ, args.json)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"ready={str(ready).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
