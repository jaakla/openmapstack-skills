"""Execute the shipped City2Graph examples against independent tiny oracles.

Opt in with OPENMAPSTACK_CITY2GRAPH_TESTS=1 after installing
evals/requirements-city2graph.txt. Missing dependencies then fail, never skip.
No public datasets, network services, Torch, or paid agent calls are required.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import unittest


GUIDE = (
    Path(__file__).resolve().parents[1]
    / "skills/open-map-stack/references/spatial-graphs.md"
)


def run_example(name):
    pattern = rf"```python\n(# city2graph-example: {re.escape(name)}\n.*?)\n```"
    blocks = re.findall(pattern, GUIDE.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1:
        raise AssertionError(f"Expected one runnable {name} example, found {len(blocks)}")
    namespace = {"__name__": "__city2graph_example__"}
    exec(compile(blocks[0], f"{GUIDE}:{name}", "exec"), namespace)
    return namespace


@unittest.skipUnless(
    os.environ.get("OPENMAPSTACK_CITY2GRAPH_TESTS") == "1",
    "optional City2Graph runtime; set OPENMAPSTACK_CITY2GRAPH_TESTS=1",
)
class City2GraphExampleTests(unittest.TestCase):
    def assert_proximity(self, result):
        nodes, edges = result["mapped_nodes"], result["mapped_edges"]
        expected = {
            "a": (650000, 6470000, 1 / 3),
            "b": (650030, 6470040, 2 / 3),
            "c": (650090, 6470040, 1 / 3),
            "isolated": (650500, 6470000, 0),
        }
        self.assertEqual(set(nodes.index), set(expected))
        self.assertTrue(nodes.index.is_unique)
        self.assertEqual(nodes.crs.to_epsg(), 3301)
        self.assertEqual(edges.crs.to_epsg(), 3301)
        self.assertFalse(result["G"].is_directed())
        for node_id, (x, y, centrality) in expected.items():
            row = nodes.loc[node_id]
            self.assertEqual((row.geometry.x, row.geometry.y), (x, y))
            self.assertAlmostEqual(row["degree_centrality"], centrality)
        weights = {
            frozenset(pair): row["weight"] for pair, row in edges.iterrows()
        }
        self.assertEqual(len(edges), 2)
        self.assertEqual(set(weights), {frozenset(("a", "b")), frozenset(("b", "c"))})
        self.assertAlmostEqual(weights[frozenset(("a", "b"))], 50)
        self.assertAlmostEqual(weights[frozenset(("b", "c"))], 60)
        self.assertTrue(edges.geometry.is_valid.all())
        for _, row in edges.iterrows():
            self.assertAlmostEqual(row.geometry.length, row["weight"])

    def assert_directed_od(self, result):
        nodes, edges = result["restored_nodes"], result["restored_edges"]
        self.assertTrue(result["flow_graph"].is_directed())
        self.assertEqual(set(nodes.index), {"a", "b", "c"})
        self.assertTrue(nodes.index.is_unique)
        self.assertEqual(nodes.crs.to_epsg(), 3301)
        self.assertEqual(edges.crs.to_epsg(), 3301)
        self.assertEqual(len(edges), 3)
        self.assertEqual(
            edges["trips"].to_dict(),
            {("a", "b"): 10, ("b", "a"): 3, ("b", "c"): 5},
        )
        self.assertEqual(edges["trips"].sum(), 18)

    def test_projected_proximity_round_trip(self):
        self.assert_proximity(run_example("proximity"))

    def test_directed_od_round_trip(self):
        self.assert_directed_od(run_example("directed-od"))

    def test_proximity_oracle_rejects_lost_source_ids(self):
        result = run_example("proximity")
        self.assert_proximity(result)
        result["mapped_nodes"] = result["mapped_nodes"].reset_index(drop=True)
        with self.assertRaises(AssertionError):
            self.assert_proximity(result)

    def test_od_oracle_rejects_reversed_flows_with_same_total(self):
        result = run_example("directed-od")
        self.assert_directed_od(result)
        result["restored_edges"] = result["restored_edges"].copy()
        result["restored_edges"].loc[("a", "b"), "trips"] = 3
        result["restored_edges"].loc[("b", "a"), "trips"] = 10
        with self.assertRaises(AssertionError):
            self.assert_directed_od(result)


if __name__ == "__main__":
    unittest.main()
