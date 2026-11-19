# Spatial graphs with City2Graph

Use [City2Graph](https://city2graph.net/latest/) when the analysis needs explicit
relationships among geographic features: buildings and streets, transit stops,
origin–destination flows, neighboring points, or adjacent zones. Keep spatial
filtering and aggregation in DuckDB/PostGIS where appropriate, then construct
the bounded graph in Python. City2Graph is an optional analysis dependency.

## Contents

- [Choose the graph](#choose-the-graph)
- [Prepare inputs and runtime](#prepare-inputs-and-runtime)
- [Proximity graph and mapped results](#proximity-graph-and-mapped-results)
- [Directed origin-destination flows](#directed-origin-destination-flows)
- [Urban morphology and GeoAI](#urban-morphology-and-geoai)
- [Transit graphs and estimated schedules](#transit-graphs-and-estimated-schedules)
- [Validate and reproduce](#validate-and-reproduce)

## Choose the graph

| Analytical need | City2Graph entry point | Decision to make explicit |
|---|---|---|
| Building–street relationships and urban form | `morphological_graph` | Node and relation types, street connectivity, tessellation and study boundary |
| Transit network structure from a GTFS feed | `load_gtfs`, `travel_summary_graph` | Service dates, time window and summary-cost interpretation |
| Commuting, migration or other OD flows | `od_matrix_to_graph` | Direction, flow units, filtering, aggregation and self-loops |
| Nearby points or adjacent polygons | `knn_graph`, `fixed_radius_graph`, `contiguity_graph` | Distance metric, k/radius or queen/rook adjacency |
| GIS graph to general graph algorithms | `gdf_to_nx`, `nx_to_gdf` | Stable source IDs, direction, parallel edges and weight semantics |
| Typed graph to GNN input | `gdf_to_pyg` | Feature/label columns, relation types, reverse edges and train/test split |

Keep OSMnx for acquiring and analyzing OSM street networks. Use City2Graph when
combining those networks with other feature types or converting graph formats.
Keep Valhalla/OSRM or a suitable hosted engine for route-serving workloads;
use r5py or another schedule-aware engine for departure-time transit journeys.
See [network analysis](analytics.md#network-analysis) for those choices.

## Prepare inputs and runtime

1. Verify the selected release's supported Python and dependency versions in the
   [installation guide](https://city2graph.net/latest/installation.html), then
   lock the resolved environment. The core `city2graph` package supports graph
   construction and NetworkX analysis without PyTorch. Install a compatible
   PyTorch/PyG extra only when a GNN workflow needs it.
2. Obtain and pin real inputs using [data discovery](data-sources.md): retain the
   Overture release, OSM snapshot or original GTFS archive, source license and
   retrieval evidence. A live loader call alone is not a reproducible input.
3. Clip to an explicit study area, retaining a documented boundary margin where
   paths may leave and re-enter it. Estimate nodes, edges and memory before
   building an in-memory graph; proximity and metapath expansion can be dense.
4. Assign unique, non-null stable feature IDs. Use node indices and edge
   MultiIndices to express connectivity; do not rely on row position or apparent
   line intersections. Keep node types separate in heterogeneous graphs.
5. Reproject metric calculations to an appropriate local projected CRS and check
   its units. Use the same CRS throughout the graph; reject missing CRS or empty
   and invalid geometries before construction. See [formats and CRS](formats-and-crs.md).

## Proximity graph and mapped results

This is a synthetic API example, not real Tartu data. Its radius describes
straight-line proximity; it does not establish walkability across barriers.

```python
# city2graph-example: proximity
import city2graph as c2g
import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import Point

points = gpd.GeoDataFrame(
    {"category": ["school", "stop", "shop", "clinic"]},
    index=pd.Index(["a", "b", "c", "isolated"], name="poi_id"),
    geometry=[
        Point(650000, 6470000), Point(650030, 6470040),
        Point(650090, 6470040), Point(650500, 6470000),
    ],
    crs="EPSG:3301",
)
nodes, edges = c2g.fixed_radius_graph(
    points, radius=75, distance_metric="euclidean"
)
G = c2g.gdf_to_nx(nodes, edges, directed=False, keep_geom=True)
nx.set_node_attributes(G, nx.degree_centrality(G), "degree_centrality")
mapped_nodes, mapped_edges = c2g.nx_to_gdf(G)

assert set(mapped_nodes.index) == set(points.index)
assert mapped_nodes.crs == points.crs
assert mapped_edges.crs == points.crs
print(mapped_nodes[["category", "degree_centrality"]].sort_index())
```

The expected links are a–b (50 m) and b–c (60 m); the fourth point stays
isolated. The proximity edge `weight` holds the chosen distance. Degree
centrality counts connections and ignores that weight. For weighted shortest
paths, pass the intended cost attribute explicitly and verify its units.

City2Graph may relabel nodes to integer keys in NetworkX while retaining source
IDs in conversion metadata. Attach results to those graph keys and convert back
with `nx_to_gdf`, as above. Do not directly join a NetworkX metric dictionary to
the original string-ID index. Preserve graph metadata and verify the returned IDs.

For street-distance proximity, supply the documented `network_gdf` and, where
needed, `network_weight`. Check snapping, disconnected components, direction and
access rules against a small known route before describing an edge as reachable.
Prefer separate `gdf_to_nx` conversion over the deprecated `as_nx` argument.

## Directed origin-destination flows

Keep direction explicit at both construction and conversion. OD construction
defaults to directed, but `gdf_to_nx` defaults to undirected. This self-contained
synthetic example preserves different a→b and b→a flows:

```python
# city2graph-example: directed-od
import city2graph as c2g
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

zones = gpd.GeoDataFrame(
    {"zone_id": ["a", "b", "c"]},
    geometry=[Point(650000, 6470000), Point(650030, 6470040),
              Point(650090, 6470040)],
    crs="EPSG:3301",
)
flows = pd.DataFrame({
    "origin": ["a", "b", "b"],
    "destination": ["b", "a", "c"],
    "trips": [10, 3, 5],
})
flow_nodes, flow_edges = c2g.od_matrix_to_graph(
    flows, zones, zone_id_col="zone_id",
    source_col="origin", target_col="destination", weight_cols=["trips"],
    directed=True, include_self_loops=False,
)
flow_graph = c2g.gdf_to_nx(flow_nodes, flow_edges, directed=True)
restored_nodes, restored_edges = c2g.nx_to_gdf(flow_graph)

assert flow_graph.is_directed()
assert restored_edges.loc[("a", "b"), "trips"] == 10
assert restored_edges.loc[("b", "a"), "trips"] == 3
assert restored_edges["trips"].sum() == 18
```

A flow count measures interaction strength, not distance or travel time. Do not
pass it unchanged to a shortest-path cost calculation. Record any transformation
and its rationale. OD edge lines connect zone representatives; they are not
observed trajectories. Verify unmatched zone IDs, zero/negative values, repeated
OD pairs and excluded self-flows before reporting totals. If choosing undirected
aggregation, use the builder's documented reciprocal-sum behavior and verify
totals; an undirected conversion alone is not a flow-aggregation operation.

## Urban morphology and GeoAI

Load pinned buildings and street segments, normalize their CRS and IDs, then
follow the [morphology API](https://city2graph.net/latest/api/morphology.html).
`morphological_graph(buildings, segments, center_point, distance=...)` returns
dictionaries of typed node and edge frames. Supply the center as a GeoSeries or
GeoDataFrame in the same CRS; `distance` limits shortest-path reach along the
street network. Inspect tessellation boundaries and source-ID mappings; select
`keep_buildings=True` if original building information is required. Verify the
release's building–street link semantics. A nearby street does not prove that a
building has an accessible entrance there; retain entrance uncertainty.

Inspect each node type and relation before conversion. Keep relation keys as
`(source_type, relation, target_type)` triples. Pass `directed` and `multigraph`
deliberately when exporting: distinct relations or parallel links must not be
silently collapsed. Metapaths (`add_metapaths`) compose existing relations;
record the sequence and aggregation rule, and inspect the resulting edge growth.

For GeoAI, use the [PyG conversion API](https://city2graph.net/latest/api/graph.html)
to select numeric feature and label columns explicitly. Check missing values,
feature scaling, source-ID mappings and reverse-edge policy before creating
`Data`/`HeteroData`. Conversion prepares tensors; model choice, training and
evaluation remain separate work. Prevent target leakage and use spatial or
temporal holdouts suited to the inference question. Report graph construction
parameters, random seeds and held-out performance with any learned result.

## Transit graphs and estimated schedules

Prefer an authoritative, archived GTFS feed. Use `load_gtfs` and
`travel_summary_graph` following the
[transportation API](https://city2graph.net/latest/api/transportation.html).
Select service dates and time bounds explicitly; inspect calendars, exceptions,
agency time zones, trips after midnight and omitted stops. Verify edge cost units
and summary aggregation before computing centrality or accessibility. Pass
`directed=True` when directional service matters; `travel_summary_graph` otherwise
defaults to undirected. Its `travel_time_sec` is a service-weighted average, not
a departure-specific duration; `frequency` counts service traversals over the
selected dates, not passengers. A static summary graph does not guarantee a
feasible itinerary with waiting and transfers.

`load_osm_transport` can construct a synthetic GTFS feed from OSM route data.
Treat this as a modeled scenario: route completeness, stop order, speeds,
headways and operating hours need evidence or explicit assumptions. Never label
the resulting times as an operator timetable or observed service. Prefer real
GTFS when available; otherwise surface the estimated-schedule limitation in
findings and maps, retain generation parameters, and test sensitivity to them.
Inspect the generated feed's assumptions through `get_gtfs_summary` and pin the
service date rather than accepting a moving default.

## Validate and reproduce

For a material analysis, apply [the project workflow](project-workflow.md).
Record the graph construction as canonical pipeline steps, with the environment,
input pins, study boundary, node/edge rules, thresholds, units, direction,
self-loop policy and any randomness. Export GIS results with stable IDs and
explicit endpoint/type columns; retain conversion metadata needed for reruns.

Check input/output feature counts, endpoint membership, direction, parallel-edge
handling, isolates and connected components. Check distances or travel costs
against small independently known examples; reconcile OD totals through every
filter. Verify geometry, CRS, IDs and required attributes after round-trips.
Report excluded or unreachable features instead of silently dropping them, and
carry source licenses and analytical limitations into delivered findings.

Use the upstream [proximity](https://city2graph.net/latest/api/proximity.html),
[mobility](https://city2graph.net/latest/api/mobility.html) and
[conversion](https://city2graph.net/latest/api/utils.html) references to verify
signatures against the pinned release. A passing tiny graph example establishes
API compatibility and its checked invariants, not source completeness or
city-scale predictive accuracy.
