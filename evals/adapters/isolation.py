"""Rootless Bubblewrap isolation for live agent runs.

A live trial is release evidence only if the agent could not read what the
evidence is meant to exclude: this repository (expected answers, tests,
unshipped docs), the maintainer's home directory, installed skills and agent
credentials. The agent sees an allowlist instead: system ``/usr`` and a few
``/etc`` files, the Python runtime that runs the evals, the shipped
``openmapstack`` package, the DuckDB extension directory, the agent CLI and
the trial workspace. Everything else under ``/home``, ``/root`` and ``/tmp``
is an empty tmpfs.

Allowlisted host paths keep their own absolute paths inside the sandbox, so
editable installs, virtualenv links and recorded workspace paths stay valid.
Only the workspace is writable. The network is shared because the agent must
reach its provider. Linux-only; runs fail closed when user namespaces are
unavailable.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from openmapstack.checks.spatial import EXTENSION_DIR_ENV

from .base import cli_version

SCHEMA = "openmapstack-live-isolation/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "openmapstack"
ETC_FILES = ("passwd", "group", "hosts", "resolv.conf", "nsswitch.conf", "localtime", "ssl", "ca-certificates")
BIN_DIR = "/opt/bin"


@functools.cache
def unavailable_reason() -> str | None:
    """Why a sandbox cannot be created here, or ``None`` when it can (a host fact)."""
    if not sys.platform.startswith("linux"):
        return f"Bubblewrap isolation requires Linux, not {sys.platform}"
    if shutil.which("bwrap") is None:
        return "`bwrap` (Bubblewrap) was not found on PATH"
    try:
        probe = subprocess.run(
            ["bwrap", "--unshare-user", "--ro-bind", "/", "/", "true"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"bwrap probe failed: {type(exc).__name__}: {exc}"
    if probe.returncode:
        return "bwrap cannot create an unprivileged namespace: " + (probe.stderr.strip() or f"status {probe.returncode}")
    return None


@functools.cache
def bwrap_version() -> str | None:
    return cli_version("bwrap")


def symlink_chain(path: Path) -> list[tuple[str, Path]]:
    """Every ``(link target, link path)`` crossed while resolving ``path``.

    Bubblewrap binds resolved trees, so a path reached through a symlinked
    directory (a uv ``cpython-3.12`` alias, a ``~/.local/bin`` launcher)
    dangles inside the sandbox unless each link is recreated.
    """
    links: list[tuple[str, Path]] = []
    pending = Path(os.path.abspath(path))
    for _ in range(40):
        current = Path("/")
        for index, part in enumerate(pending.parts[1:], start=1):
            current = current / part
            if current.is_symlink():
                target = os.readlink(current)
                links.append((target, current))
                pending = Path(os.path.normpath(current.parent / target)).joinpath(*pending.parts[index + 1:])
                break
        else:
            return links
    raise OSError(f"too many symbolic links resolving {path}")


def spatial_extension_dir() -> Path:
    configured = os.environ.get(EXTENSION_DIR_ENV)
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".duckdb" / "extensions"


@dataclass
class Sandbox:
    """Allowlist for one agent process; ``argv`` is the bwrap prefix."""

    workspace: Path
    executables: dict[str, Path] = field(default_factory=dict)
    read_only: list[Path] = field(default_factory=list)
    interpreter: Path | None = None
    variables: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_python_agent(cls, workspace: Path, executables: dict[str, Path]) -> "Sandbox":
        """Expose the running interpreter, the shipped package and DuckDB extensions."""
        extensions = spatial_extension_dir()
        read_only = [Path(sys.prefix), Path(sys.base_prefix), PACKAGE_DIR, extensions]
        # Import the package under test even when the interpreter's editable
        # install points at another checkout; nothing else of the repository
        # is mounted under this root.
        variables = {"PYTHONPATH": str(PACKAGE_DIR.parent), EXTENSION_DIR_ENV: str(extensions)}
        return cls(workspace, dict(executables), read_only, Path(sys.executable), variables)

    def visible_paths(self) -> list[str]:
        paths = {str(path.resolve()) for path in self.read_only if path.exists()}
        return sorted(path for path in paths if not path.startswith("/usr/"))

    def argv(self, cwd: Path) -> list[str]:
        command = [
            "bwrap", "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
            "--die-with-parent", "--new-session",
            "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--tmpfs", "/home", "--tmpfs", "/root", "--dir", str(Path.home()),
        ]
        for name in ("bin", "sbin", "lib", "lib32", "lib64"):
            host = Path("/") / name
            if host.is_symlink():
                command.extend(["--symlink", os.readlink(host), str(host)])
            elif host.is_dir():
                command.extend(["--ro-bind", str(host), str(host)])
        for name in ETC_FILES:
            host = Path("/etc") / name
            if host.exists():
                command.extend(["--ro-bind", str(host), str(host)])
        visible_paths = self.visible_paths()
        for path in visible_paths:
            command.extend(["--ro-bind", path, path])
        visible = [Path("/usr"), *map(Path, visible_paths)]
        for host in sorted({executable.resolve() for executable in self.executables.values()}):
            if not any(host.is_relative_to(path) for path in visible):
                command.extend(["--ro-bind", str(host), str(host)])
                visible.append(host)
        recreated: set[Path] = set()
        linked = [*self.read_only, *self.executables.values(), *([self.interpreter] if self.interpreter else [])]
        for host in linked:
            for target, link in symlink_chain(host):
                if link not in recreated and not any(link.is_relative_to(path) for path in visible):
                    command.extend(["--symlink", target, str(link)])
                    recreated.add(link)
        command.extend(["--dir", BIN_DIR])
        for name, host in sorted(self.executables.items()):
            command.extend(["--symlink", os.path.abspath(host), f"{BIN_DIR}/{name}"])
        workspace = str(self.workspace.resolve())
        command.extend(["--bind", workspace, workspace, "--chdir", str(cwd.resolve())])
        return command

    def environment(self, extra: dict[str, str]) -> dict[str, str]:
        # An interpreter's own bin/ goes on PATH rather than behind a link:
        # a virtualenv locates pyvenv.cfg from the path it was invoked by.
        interpreter_dir = [os.path.dirname(os.path.abspath(self.interpreter))] if self.interpreter else []
        environment = {
            "PATH": ":".join([BIN_DIR, *interpreter_dir, "/usr/local/bin", "/usr/bin", "/bin"]),
            "HOME": str(Path.home()),
            "LANG": "C.UTF-8",
            "TMPDIR": "/tmp",
            **self.variables,
        }
        environment.update(extra)
        return environment

    def evidence(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "kind": "bubblewrap_allowlist",
            "bwrap": bwrap_version(),
            "writable": [str(self.workspace.resolve())],
            "read_only": ["/usr", *self.visible_paths()],
            "executables": {name: str(path) for name, path in sorted(self.executables.items())},
            "interpreter": os.path.abspath(self.interpreter) if self.interpreter else None,
            "variables": dict(sorted(self.variables.items())),
            "network": "shared",
        }


RERUN_SCRIPT = """
import json, sys
from pathlib import Path
from openmapstack.rerun import perform_clean_rerun
project, rerun, timeout, forbidden = sys.argv[1], sys.argv[2], float(sys.argv[3]), json.loads(sys.argv[4])
evidence = perform_clean_rerun(Path(project), Path(rerun), timeout, forbidden_fragments=forbidden)
print(json.dumps(evidence, default=str))
"""


def sandboxed_clean_rerun(
    project: Path, rerun: Path, timeout_s: float, forbidden_fragments: tuple[str, ...] = ()
) -> dict[str, object]:
    """Run ``perform_clean_rerun`` on an agent-written project inside the sandbox.

    The canonical pipeline a live agent delivered is untrusted code; the host
    runner must not execute it. The delivered project is read-only here and
    only the rerun workspace is writable. Fails closed when no sandbox exists.
    """
    def failed(error: str) -> dict[str, object]:
        return {"status": "failed", "stage": "isolation", "error": error}

    reason = unavailable_reason()
    if reason:
        return failed(f"refusing an unisolated clean rerun: {reason}")
    sandbox = Sandbox.for_python_agent(rerun, {})
    sandbox.read_only.append(project.resolve())
    argv = [
        *sandbox.argv(rerun),
        "python3", "-c", RERUN_SCRIPT,
        str(project.resolve()), str(rerun.resolve()), str(timeout_s), json.dumps(list(forbidden_fragments)),
    ]
    limit = timeout_s + 120
    try:
        proc = subprocess.run(argv, env=sandbox.environment({}), capture_output=True, text=True, timeout=limit, check=False)
    except subprocess.TimeoutExpired:
        return failed(f"sandboxed clean rerun exceeded {limit}s")
    try:
        evidence = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return failed(f"sandboxed clean rerun produced no evidence (status {proc.returncode}): {proc.stderr[-400:]}")
    evidence["isolation"] = sandbox.evidence()
    return evidence

