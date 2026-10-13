# Bounded raster access examples

These are small processing examples, not a complete material-analysis project.
`raster_access.py` is also included in the installed project-capable skills.
Copy this directory to a writable workspace and prepare an isolated environment:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

The requirements pin the integration environment tested for issue #93. Verify
upstream capabilities when choosing another environment; these packages remain
optional. The GDAL stack here uses tested binary wheels, rather than assuming
every pip-only native environment works.

## Lazy reprojection with an explicit grid

Choose the source window from the actual AOI and source transform, including
the interpolation support around it. Choose a destination grid from the
analysis requirements. The numbers below illustrate a small Estonian raster;
they are not a general CRS, chunk size or memory recommendation.

```python
from affine import Affine
from odc.geo.geobox import GeoBox
import rioxarray
from raster_access import reproject_aoi

grid = GeoBox((128, 192), Affine(10, 0, 660000, 0, -10, 6470000), "EPSG:3301")
with rioxarray.open_rasterio(
    "input.tif", chunks={"band": 1, "y": 256, "x": 256}, masked=True,
) as source:
    warped = reproject_aoi(
        source, source_window=(0, 256, 0, 256), destination_grid=grid,
        resampling="nearest", src_nodata=float("nan"), dst_nodata=float("nan"),
        chunks=(64, 64), warp_options={"tolerance": 0, "XSCALE": 1, "YSCALE": 1},
    )
    # Graph construction above does not read the source pixel array.
    # Explicit eager boundary: only this small, budgeted output fits in memory.
    small = warped.compute(scheduler="threads", num_workers=2)
    small.rio.to_raster("aoi.tif", driver="COG", compress="DEFLATE")
```

The example disables approximate coordinate transformation (`tolerance=0`) and
fixes the interpolation scale for this near-equal-resolution warp. Approximate
transformers and automatic sampling scale can otherwise give different pixels
in full-array and chunked warps. For deliberate downsampling, choose an
appropriate aggregation/kernel policy instead of copying this scale setting;
match it in the oracle. This uses the tested rasterio runtime's `tolerance`
argument, which older releases may not expose.

Nearest resampling preserves class codes; choose bilinear/cubic for continuous
measurements only when appropriate. `masked=True` maps input nodata to NaN but
does not apply physical scale/offset; the warp therefore explicitly receives
NaN as its **in-memory** source nodata, rather than the file's encoded sentinel.
Inspect and apply physical scale/offset separately if
needed. Check output pixels, masks, CRS, transform and footprint against an
independent rasterio/GDAL warp using the same explicit grid. A chunked source
does not make `.rio.reproject()` lazy. For a large output, avoid this eager
`.compute()` boundary: use a verified streaming/chunked writer such as the
[odc-geo Dask COG writer](https://odc-geo.readthedocs.io/en/latest/_api/odc.geo.cog.save_cog_with_dask.html)
with its optional codec dependencies, or a bounded GDAL warp/write pipeline.

## Async COG windows, explicit overview and finite retries

```python
import asyncio
from datetime import timedelta
from async_geotiff import Window
from obstore.store import HTTPStore
from raster_access import cog_windows

async def main():
    store = HTTPStore(
        "https://your-data-origin.example/",
        client_options={"timeout": "10s"},
        retry_config={"max_retries": 2, "retry_timeout": timedelta(seconds=20)},
    )
    windows = [Window(col_off=128, row_off=64, width=64, height=64)]
    async for raster in cog_windows(
        store, "pinned-image.tif", windows=windows, overview=None,
        concurrency=2, max_window_pixels=65536, timeout=30,
    ):
        values = raster.as_masked()
        # Consume/reduce/write this result, retaining raster.crs and
        # raster.transform. Do not accumulate every window into a huge list.
        print(values.shape, raster.crs, raster.transform)

asyncio.run(main())
```

`overview=None` explicitly chooses original resolution. To use an overview,
inspect its shape/resolution and pass its nonnegative index (finest first);
windows then refer to that overview's pixels. No resampling or automatic
overview choice occurs. The helper limits simultaneous **window reads** and
pixels per window, not total process memory or internal HTTP request count:
decoders fetch whole intersecting storage tiles, may coalesce requests and
prefetch metadata, and need additional buffers. Budget bands, dtype, decoded
tile sizes and in-flight work as well as returned pixels. The caller controls
storage authentication; never put secrets into source identifiers.

`RasterArray.mask` uses True for valid data. Use `.as_masked()` when consuming
NumPy masked arrays, whose mask convention is the reverse. Preserve masks,
nodata, CRS, window transform and source scale/offset; raw samples are not
automatically physical measurements. Unsupported codecs, invalid windows,
timeouts and transport failures propagate as errors, not empty/zero arrays.
async-geotiff is a reader; use GDAL/rasterio or a verified lazy warp for
reprojection, resampling and output writing.

## Reproduce the integration evidence

From the repository root, with the optional environment above:

```bash
OPENMAPSTACK_RASTER_TESTS=1 .venv/bin/python -m unittest -v tests.test_raster_access
```

The tests generate asymmetric synthetic rasters, compare independent numerical
oracles, observe Dask source reads, and use a loopback HTTP range server for
actual COG reads and failures. They need no public data, model account or cloud
credentials. Missing optional packages fail when explicitly selected; ordinary
core test runs skip this capability. Behavioral prompts and evidence limits are
documented in `evals/raster-access.md` in the repository, not shipped as answers
inside the skill.
