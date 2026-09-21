"""Shipped corrections that a live acceptance run caught must not silently revert.

The 0.4.0 acceptance run (see `docs/release-0.4.0.md`) found two task-outcome
failures that traced to shipped guidance rather than to the adapter or model:
an agent claimed a plain `geom` GiST index serves a `::geography` predicate, and
another treated a WFS `resultType=hits` total as proof of completeness. Both
sentences were corrected, and both reruns then passed.

Nothing else in the repository can notice if that wording goes away. The routing
eval grades *selection* only -- `evals/routing.py` reports `task_success` as
`not_testable` by construction -- and the fixture evals grade produced projects,
not the reference text an agent reads before producing one. So a later edit
could reintroduce either error and every automated check would stay green.

These are content assertions, and that is their whole claim: they prove the
corrective guidance is still shipped in every payload that carries the file, and
that the retracted advice has not come back. They do **not** prove an agent
reads it or acts on it. That remains the job of the live cases
`chosen-engine-sql` and `bounded-discovery` in `evals/routing-cases.yaml`, graded
against the rubric in `evals/final-state-acceptance.md`.

Rewording a requirement intentionally means updating the assertion *and*
re-running the owning live case, not just relaxing the string.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"


def _shipped_copies(name: str) -> dict[str, str]:
    """Every skill payload that ships `references/<name>`, keyed by repo path."""
    copies = {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in sorted(SKILLS_ROOT.glob(f"*/references/{name}"))
    }
    assert copies, f"no shipped copy of references/{name}"
    return copies


class GuidanceCase(unittest.TestCase):
    """Substring assertions that report the needle, not the whole payload."""

    def assertShips(self, text: str, needle: str, path: str) -> None:
        self.assertTrue(needle in text, f"{path} no longer ships: {needle!r}")

    def assertRetracted(self, text: str, needle: str, path: str) -> None:
        self.assertTrue(needle not in text, f"{path} reintroduced retracted advice: {needle!r}")


class GeographyIndexGuidanceTests(GuidanceCase):
    """`chosen-engine-sql`: an index serves only the expression it was built on."""

    def setUp(self) -> None:
        self.copies = _shipped_copies("spatial-sql.md")

    def test_every_copy_states_that_a_cast_defeats_the_geometry_index(self) -> None:
        for path, text in self.copies.items():
            with self.subTest(path=path):
                self.assertShips(text, "An index serves only the expression it was built on.", path)
                self.assertShips(text, "ST_DWithin(p.geom::geography, s.geom::geography, 500)", path)

    def test_every_copy_offers_an_index_matching_the_predicate(self) -> None:
        for path, text in self.copies.items():
            with self.subTest(path=path):
                self.assertShips(text, "USING GIST ((geom::geography))", path)
                self.assertShips(text, "USING GIST (ST_Transform(geom, 3301))", path)

    def test_every_copy_names_the_plan_evidence_to_check(self) -> None:
        """A recommendation with no way to verify it is what failed the first time."""
        for path, text in self.copies.items():
            with self.subTest(path=path):
                self.assertShips(text, "Index Cond", path)
                self.assertShips(text, "Join Filter", path)

    def test_the_retracted_bare_column_advice_is_gone(self) -> None:
        """This exact sentence is what the failing trial followed."""
        retracted = "Create GIST indexes on production geometry columns"
        for path, text in self.copies.items():
            with self.subTest(path=path):
                self.assertRetracted(text, retracted, path)


class PaginationCompletenessGuidanceTests(GuidanceCase):
    """`bounded-discovery`: completeness comes from the paged total, not from hits."""

    def test_validation_checklist_rejects_a_bare_hits_request(self) -> None:
        for path, text in _shipped_copies("validation-and-ops.md").items():
            with self.subTest(path=path):
                self.assertShips(text, "A separate hits/count request is not proof on its own", path)
                self.assertRetracted(text, "pagination or a hits/count request proves completeness", path)

    def test_etak_paging_recipe_pages_to_the_reported_total(self) -> None:
        for path, text in _shipped_copies("data-sources.md").items():
            with self.subTest(path=path):
                for needle in ("sortBy", "startIndex", "numberMatched"):
                    self.assertShips(text, needle, path)
                self.assertShips(text, "Do not use `resultType=hits` as the completeness total", path)

    def test_the_worked_example_pages_the_way_the_guidance_says(self) -> None:
        """Guidance and the canonical example must not drift apart."""
        pipeline = (REPO_ROOT / "examples/tartu-development/pipeline.py").read_text(encoding="utf-8")
        self.assertIn("numberMatched", pipeline)
        self.assertIn("startIndex", pipeline)
        self.assertNotIn("resultType=hits", pipeline)


class VerifiedBackendGuidanceTests(GuidanceCase):
    """What the CLI can connect to, and what the shipped text claims, are one list.

    A backend the connector supports but the guidance still calls unsupported
    sends an agent off to the vendor CLI and an unpinned hand-copied file; a
    backend the guidance promises but the connector refuses fails at the first
    `source discover`. Either drift is silent, so the list is asserted from
    `connectors.BACKENDS` rather than transcribed.
    """

    def test_every_copy_names_the_backends_the_connector_actually_supports(self) -> None:
        from openmapstack.connectors import BACKENDS

        for path, text in _shipped_copies("user-data-sources.md").items():
            with self.subTest(path=path):
                for backend in BACKENDS:
                    self.assertShips(text, backend, path)

    def test_no_copy_still_calls_a_supported_backend_unsupported(self) -> None:
        from openmapstack.connectors import BACKENDS

        for path, text in _shipped_copies("user-data-sources.md").items():
            unsupported = text.split("## Other backends", 1)
            self.assertEqual(len(unsupported), 2, f"{path} no longer has an 'Other backends' section")
            listed = unsupported[1].split("For those:", 1)[0]
            for backend in BACKENDS:
                with self.subTest(path=path, backend=backend):
                    self.assertNotIn(
                        f"`{backend}`",
                        listed,
                        f"{path} lists the supported backend {backend!r} as one the CLI refuses",
                    )

    def test_the_metered_backend_ships_its_two_traps(self) -> None:
        """BigQuery's cost guard and its row-count caveat are the reasons this
        backend is not just 'another SQL database'."""
        for path, text in _shipped_copies("user-data-sources.md").items():
            with self.subTest(path=path):
                self.assertShips(text, "max-scan-bytes", path)
                self.assertShips(text, "scan_limit_exceeded", path)
                self.assertShips(text, "is not what your reader can see", path)

    def test_the_motherduck_confinement_limit_is_stated_not_implied_away(self) -> None:
        for path, text in _shipped_copies("user-data-sources.md").items():
            with self.subTest(path=path):
                self.assertShips(text, "a MotherDuck session needs network access", path)
                self.assertShips(text, "READ_ONLY", path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
