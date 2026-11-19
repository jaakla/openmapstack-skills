# City2Graph example checks

Run the two Python examples shipped in
[the spatial graph reference](../skills/open-map-stack/references/spatial-graphs.md)
against small synthetic inputs with independently known answers. These checks
exercise the real library without downloading geographic data or calling an
agent. City2Graph is an optional analysis tool, not an OpenMapStack CLI dependency.

Use an isolated Python 3.12 environment:

```bash
python -m pip install -r evals/requirements-city2graph.txt
OPENMAPSTACK_CITY2GRAPH_TESTS=1 python -m unittest -v tests.test_city2graph_examples
```

The checks execute the marked code blocks from the installed guidance itself,
so examples and test implementations cannot silently diverge. They verify:

- A metric fixed-radius graph contains only the two expected edges, weighted
  50 m and 60 m, and retains an isolated point.
- NetworkX analysis and conversion back to GeoDataFrames preserve source IDs,
  geometries, CRS, and correctly aligned degree centrality.
- Asymmetric OD flows retain direction and their individual values (10, 3, 5),
  not merely their total, after graph conversion.
- The same oracles reject lost source IDs and swapped opposing flows, with
  a healthy control executed before each mutation.

Ordinary unit runs skip these checks unless explicitly selected. With the flag
set, missing dependencies or broken examples fail. The focused CI workflow
installs the optional runtime and enables the checks on relevant changes.

This establishes example compatibility with the pinned City2Graph release and
the resolved dependencies in that run. It does not validate large-city scale,
real-data completeness, GTFS service quality, morphology/GNN training, or live
agent adherence to the guidance. No paid trial is implied or authorized.
