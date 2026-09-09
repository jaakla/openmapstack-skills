"""SKILL.md is a router, so its pointers must resolve (issue #26).

`SKILL.md` is the always-loaded entry point: consuming agents read it and then
open whichever `references/*.md` it names. A pointer to a file that does not
exist sends an agent looking for guidance that is not there, and a reference
nothing points at is guidance no agent will ever load. Neither shows up in the
fixture evals, which grade produced projects rather than the routing table.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: References SKILL.md is not required to route to, with the reason why.
UNROUTED_ALLOWED: dict[str, str] = {}


def _routed_references(skill_text: str) -> set[str]:
    return set(re.findall(r"references/[A-Za-z0-9._-]+\.md", skill_text))


class SkillRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.references = {
            f"references/{path.name}" for path in (REPO_ROOT / "references").glob("*.md")
        }

    def test_every_reference_skill_md_names_exists(self) -> None:
        missing = sorted(
            name for name in _routed_references(self.skill) if not (REPO_ROOT / name).is_file()
        )
        self.assertEqual(missing, [], f"SKILL.md routes to missing reference(s): {missing}")

    def test_every_reference_is_reachable_from_skill_md(self) -> None:
        """A reference no agent is told to read is dead weight in the payload."""
        unrouted = sorted(self.references - _routed_references(self.skill) - set(UNROUTED_ALLOWED))
        self.assertEqual(unrouted, [], f"reference(s) nothing in SKILL.md points at: {unrouted}")

    def test_portolan_routes_to_the_reference_that_documents_it(self) -> None:
        """Consuming a Portolan catalog is discovery, so it must route like it.

        This is a routing assertion and nothing more: it proves an agent
        reaching for the term lands on the section, not that the section makes
        the agent behave. Eval case `017-portolan-catalog` grades the behaviour,
        by consequence, against a fixture catalog.
        """
        self.assertIn("Portolan", self.skill)
        data_sources = (REPO_ROOT / "references/data-sources.md").read_text(encoding="utf-8")
        self.assertIn("## Portolan catalogs", data_sources)
        self.assertIn("AGENTS.md", data_sources)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
