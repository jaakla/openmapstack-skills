"""Optional raster examples; no dependency on the OpenMapStack CLI."""
from __future__ import annotations

import asyncio
from itertools import islice


def reproject_aoi(source, *, source_window, destination_grid, resampling,
                  src_nodata, dst_nodata, chunks, warp_options):
    """Build a lazy warp of an explicit pixel window onto an explicit GeoBox.

    Keep the source open until the graph is executed. The source window must
    include the resampling support/halo needed by the destination footprint.
    Chunk sizes are (rows, columns), in pixels, on the destination grid.
    """
    from dask.base import is_dask_collection
    import odc.geo.xr  # Registers .odc on xarray objects.
    import rioxarray  # Registers .rio, including explicit output nodata metadata.

    if not is_dask_collection(source.data):
        raise ValueError("source must be Dask-backed")
    row0, row1, col0, col1 = source_window
    if not (0 <= row0 < row1 <= source.sizes['y']
            and 0 <= col0 < col1 <= source.sizes['x']):
        raise ValueError("source_window must be nonempty and inside the source")
    subset = source.isel(y=slice(row0, row1), x=slice(col0, col1))
    result = subset.odc.reproject(
        destination_grid, resampling=resampling, src_nodata=src_nodata,
        dst_nodata=dst_nodata, chunks=chunks, **warp_options,
    )
    if not is_dask_collection(result.data):
        raise RuntimeError("reprojection unexpectedly materialized the raster")
    # odc-geo may omit NaN nodata attributes; output pixels alone do not make
    # a subsequent writer encode a valid nodata mask.
    return result.rio.write_nodata(dst_nodata)


async def cog_windows(store, path, *, windows, overview, concurrency=2,
                      max_window_pixels=1024 * 1024, timeout=30):
    """Yield bounded batches of explicit windows, preserving RasterArray metadata.

    `overview=None` selects the base image; an integer selects an existing
    overview, finest first. Windows use that level's pixel coordinates.
    Concurrency limits active window reads, not the reader's internal tile
    requests. Release each result after use; retaining results uses more memory.
    Configure finite transport timeouts/retries on the supplied obstore store.
    """
    from async_geotiff import GeoTIFF

    if not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("concurrency must be a positive integer")
    if max_window_pixels < 1 or timeout <= 0:
        raise ValueError("pixel limit and timeout must be positive")
    image = await asyncio.wait_for(GeoTIFF.open(path, store=store), timeout)
    if image.compression is None:
        raise ValueError("unrecognized TIFF compression; verify decoder support")
    level = image
    if overview is not None:
        if not isinstance(overview, int) or not 0 <= overview < len(image.overviews):
            raise ValueError("overview must select an existing level")
        level = image.overviews[overview]

    pending = iter(windows)
    while batch := list(islice(pending, concurrency)):
        for window in batch:
            if (window.width <= 0 or window.height <= 0
                    or window.width * window.height > max_window_pixels
                    or window.col_off < 0 or window.row_off < 0
                    or window.col_off + window.width > level.width
                    or window.row_off + window.height > level.height):
                raise ValueError("window exceeds the selected level or pixel budget")
        tasks = [asyncio.create_task(asyncio.wait_for(level.read(window=w), timeout))
                 for w in batch]
        try:
            results = await asyncio.gather(*tasks)
        finally:
            # A failed/abandoned batch must not leave sibling reads running.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            yield result
