# Focused raster behavior evaluation (#93)

This is an optional release integration/evaluation surface, separate from the
default fixture suite and generic model benchmarking. It exercises raster
libraries against local, independently checked inputs. It does not require or
authorize a paid agent trial, public data download or cloud account.

## Reference control and mutations

Prepare Python 3.12 with `examples/raster-access/requirements.txt`, then run:

```bash
OPENMAPSTACK_RASTER_TESTS=1 python -m unittest -v tests.test_raster_access
```

The eight executable checks cover:

- Graph construction without pixel reads, actual source-window observations,
  and a nontrivial CRS warp compared with a full-source rasterio oracle.
- Bilinear continuous values, nodata masks, destination transform, CRS, COG
  reopen, nearest categorical codes and output chunk edges.
- Eager-source rejection and invalid source windows. A class-value mutation
  and shifted destination grid must fail the same pixel/grid oracle.
- Real HTTP 206 reads at base resolution and an explicitly selected overview,
  compared with rasterio values/masks/window transforms. Selected reads transfer
  less than the complete fixture; this is not a universal performance threshold.
- Actual concurrent window reads limited to two, with no unbounded batch
  prefetch. This does not bound the library's internal HTTP request count.
- Invalid level, pixel-budget and out-of-bounds requests.
- Missing objects, HTTP 503 and an unsupported TIFF compression-tag mutation.
  These must raise errors with the expected causes, never return successful zeros.
- A stalled batch must time out and cancel both sibling reads. The read-stall
  injection tests cancellation, not production latency.

Core test runs skip these eight checks unless selected. When selected, missing
packages and unavailable loopback sockets fail, so missing capability cannot
produce green integration evidence. The PR workflow installs and explicitly
selects this optional runtime. Generated synthetic rasters and results are
temporary; they are not invented real-world source data.

## Agent task for an explicitly authorized behavioral trial

Start the agent in a clean workspace with the selected installed skill payload
and the pinned optional runtime. Do not provide the oracle test code or its
answers. Give it this prompt:

> We need two bounded raster operations for a GIS pipeline. Opening with chunks
> has not prevented our reprojection from exhausting memory. Implement a Python
> module `candidate.py` with the following interfaces. Keep reading and graph
> construction separate from executing/writing the output, and document the
> limits of your resource bounds in `notes.md`.
>
> `reproject_aoi(source, *, source_window, destination_grid, resampling,
> src_nodata, dst_nodata, chunks, warp_options)` accepts a Dask-backed xarray
> raster with x/y dimensions, a pixel window `(row0, row1, col0, col1)`, an odc
> GeoBox, destination `(rows, columns)` chunk sizes, and explicit rasterio warp
> options. Return a still-lazy georeferenced DataArray on the requested grid,
> preserving in-memory nodata semantics and metadata for subsequent COG output.
> Reject eager input and windows outside the source. No pixel reads should occur
> while constructing the graph. Caller keeps the source open through execution.
>
> `cog_windows(store, path, *, windows, overview, concurrency=2,
> max_window_pixels=1048576, timeout=30)` is an async iterator using an obstore
> store and async-geotiff Windows. Read only bounded batches; overview=None means
> original resolution and a nonnegative index selects an existing overview.
> Yield georeferenced RasterArray objects. Enforce window limits/deadlines,
> preserve masks/transforms/CRS, reject unrecognized compression, propagate read
> failures, and cancel in-flight siblings on failure. Transport retries are
> finite and configured by the caller. Do not claim this reader also supplies
> reprojection, resampling or output writing.

Grade the produced module with the same reference-control tests:

```bash
OPENMAPSTACK_RASTER_TESTS=1 \
OPENMAPSTACK_RASTER_CANDIDATE=/absolute/trial/workspace/candidate.py \
python -m unittest -v tests.test_raster_access
```

This executes untrusted generated code: use the established isolated live-trial
environment, not a credential-bearing production environment. Record the skill
snapshot, agent/model, runtime versions, command, return code and full results.
Candidate selection without the runtime flag is an error rather than a skip.
The grader observes executable behavior, not a candidate's declarations about
laziness or correctness. Do not aggregate this with default fixture pass rates.

Review `notes.md` separately for the operation's actual choices: eager writing
limits; source-window halo; in-memory versus encoded nodata; transformation
approximation and interpolation policy; chunk/band/dtype/worker budgeting;
overview pixel coordinates; inverted mask conventions; optional decoder/runtime
support. Geoutils is acceptable only for a verified operation, not an assumed
planned feature. A narrative-only submission fails the executable checks.

No live-agent pass is implied by a reference-control pass. No cold/warm-cache,
production throughput or memory-limit benchmark is established by these small
local correctness tests. Such measurements need their own recorded workload
and environment. Compatibility with other runtime versions is unverified until
tested.
