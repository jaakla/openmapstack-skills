"""Known-answer checks for reviewable vector-tiling command plans.

These inspect argv artifacts, not explanations, and never execute submitted code.
They prove a bounded planning decision, not runtime behavior or rendered coverage.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import AssertionResult, failed, get_in, not_testable, passed, project_root


# Deliberately bounded plan vocabulary; not a replacement for either tool's CLI.
_OPTIONS = {
    'tylertoo': {'--min-zoom': True, '--max-zoom': True, '--layer-name': True,
                '--verbatim': False},
    'tippecanoe': {'--minimum-zoom': True, '--maximum-zoom': True,
                   '--layer': True, '--output': True, '--feature-filter': True},
}


def _normalize(argv):
    if (not isinstance(argv, list) or not argv
            or not all(isinstance(arg, str) and arg for arg in argv)):
        raise ValueError('command must be a nonempty argv string array')
    tool = argv[0]
    if tool not in _OPTIONS:
        raise ValueError('unsupported tiler in bounded command plan')
    positional, options = [], {}
    index = 1
    while index < len(argv):
        token = argv[index]
        index += 1
        if not token.startswith('-'):
            positional.append(token)
            continue
        name, separator, value = token.partition('=')
        if name not in _OPTIONS[tool] or name in options:
            raise ValueError('unknown or repeated option')
        if _OPTIONS[tool][name]:
            if not separator:
                if index == len(argv) or argv[index].startswith('-'):
                    raise ValueError('missing option value')
                value = argv[index]
                index += 1
            if not value:
                raise ValueError('empty option value')
            # Compare JSON filters by meaning, not whitespace/key order.
            options[name] = json.loads(value) if name == '--feature-filter' else value
        else:
            if separator:
                raise ValueError('boolean option cannot have a value')
            options[name] = True
    return tool, positional, options


def command_matches(workspace: Path, path: str, field: str, expected: list[str],
                    project_dir: str = '.') -> AssertionResult:
    """Compare a bounded tiler argv plan with an independently supplied oracle.

    Options can be reordered or use --key=value. Extra commands, unknown flags,
    repeated overrides and missing safeguards cannot pass via a token mention.
    Expected values belong to the task reviewer, never the submitted plan.
    """
    oracle = _normalize(expected)  # Invalid oracle is a setup error.
    target = project_root(workspace, project_dir) / path
    if not target.is_file():
        return failed(f'{path} does not exist', code='file_missing')
    try:
        payload = json.loads(target.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        return failed('plan is not valid JSON', code='json_invalid')
    except OSError as exc:
        return not_testable(f'cannot read plan: {exc}', code='read_error')
    try:
        actual = _normalize(get_in(payload, field))
    except (ValueError, TypeError):
        return failed(f'{field} is not a valid bounded tiler command', code='tiler_command_invalid')
    if actual != oracle:
        return failed(f'{field} differs from the required tool/input/options',
                      code='tiler_command_mismatch')
    return passed(f'{field} matches the required tiling decision')
