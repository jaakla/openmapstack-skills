"""Optional real raster integration; no cloud, public data, or model account."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import re
import struct
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
candidate = os.environ.get("OPENMAPSTACK_RASTER_CANDIDATE")
if candidate and os.environ.get("OPENMAPSTACK_RASTER_TESTS") != "1":
    raise RuntimeError("candidate evaluation requires OPENMAPSTACK_RASTER_TESTS=1")


def load_example(path, name="raster_access_example"):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load raster example from {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


example = load_example(Path(candidate) if candidate else
                       ROOT / "examples/raster-access/raster_access.py")


class CandidateImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "candidate.py"
        self.module_name = "raster_import_regression"
        modules = patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)

    def test_postponed_annotation_dataclass_imports(self):
        self.path.write_text(
            "from __future__ import annotations\n"
            "from dataclasses import dataclass\n"
            "@dataclass\nclass Result:\n    value: int\n")
        module = load_example(self.path, self.module_name)
        self.assertIs(sys.modules[self.module_name], module)
        self.assertEqual(module.Result(3).value, 3)

    def test_failed_import_removes_partial_module(self):
        self.path.write_text("raise RuntimeError('broken candidate')\n")
        with self.assertRaisesRegex(RuntimeError, "broken candidate"):
            load_example(self.path, self.module_name)
        self.assertNotIn(self.module_name, sys.modules)

    def test_failed_import_restores_previous_module(self):
        previous = ModuleType(self.module_name)
        sys.modules[self.module_name] = previous
        self.path.write_text("raise RuntimeError('broken candidate')\n")
        with self.assertRaisesRegex(RuntimeError, "broken candidate"):
            load_example(self.path, self.module_name)
        self.assertIs(sys.modules[self.module_name], previous)


@contextmanager
def range_origin(files):
    """Deterministic loopback origin; log actual HTTP ranges and failures."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = files.get(self.path)
            if payload is None:
                self.send_error(404)
                return
            if isinstance(payload, int):
                self.send_error(payload)
                return
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
            if not match:
                self.send_error(400, "This fixture requires a bounded Range")
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else len(payload) - 1, len(payload) - 1)
            if start > end:
                self.send_error(416)
                return
            requests.append((self.path, start, end))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(payload[start:end + 1])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@unittest.skipUnless(os.environ.get("OPENMAPSTACK_RASTER_TESTS") == "1",
                     "optional raster runtime not selected (set OPENMAPSTACK_RASTER_TESTS=1)")
class RasterAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Missing packages are failures when this integration is selected.
        global np, rio, rx, Affine, GeoBox, Window, HTTPStore
        import numpy as np
        import rasterio as rio
        import rioxarray as rx
        from affine import Affine
        from odc.geo.geobox import GeoBox
        from async_geotiff import Window
        from obstore.store import HTTPStore

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, categorical=False):
        rows, cols = np.indices((512, 768))
        data = ((1 + (rows // 5 + cols // 7) % 4) if categorical
                else rows * 13 + cols * 0.17).astype("float32")
        data[235:275, 250:285] = -9999
        path = self.root / "source.tif"
        with rio.open(path, "w", driver="GTiff", width=768, height=512,
                      count=1, dtype="float32", crs="EPSG:3301",
                      transform=Affine(10, 0, 660000, 0, -10, 6470000),
                      nodata=-9999, tiled=True, blockxsize=128, blockysize=128) as dst:
            dst.write(data, 1)
        return path, data

    def warp(self, categorical=False):
        from rasterio.warp import calculate_default_transform, reproject
        from rasterio.enums import Resampling
        from rioxarray._io import RasterioArrayWrapper

        path, values = self.source(categorical)
        with rio.open(path) as src:
            # Interior destination AOI leaves interpolation support in the
            # larger explicitly selected source window.
            bounds = rio.windows.bounds(rio.windows.Window(160, 160, 320, 192), src.transform)
            transform, width, height = calculate_default_transform(
                src.crs, "EPSG:32635", 320, 192, *bounds, resolution=10)
            grid = GeoBox((height, width), transform, "EPSG:32635")
            expected = np.full((height, width), np.nan, dtype="float32")
            method = "nearest" if categorical else "bilinear"
            # Independent full-source oracle; do not reuse the cropped/Dask
            # implementation or its graph to calculate expected pixels.
            reproject(values, expected, src_transform=src.transform, src_crs=src.crs,
                      src_nodata=-9999, dst_transform=transform, dst_crs="EPSG:32635",
                      dst_nodata=np.nan, resampling=Resampling[method],
                      tolerance=0, XSCALE=1, YSCALE=1)

        reads = []
        original = RasterioArrayWrapper._getitem

        def observed(wrapper, key):
            reads.append(key)
            return original(wrapper, key)

        with rx.open_rasterio(path, masked=True,
                              chunks={"band": 1, "y": 128, "x": 128}) as src:
            with patch.object(RasterioArrayWrapper, "_getitem", observed):
                out = example.reproject_aoi(
                    src, source_window=(128, 384, 128, 512), destination_grid=grid,
                    resampling=method, src_nodata=np.nan, dst_nodata=np.nan,
                    chunks=(64, 64), warp_options={"tolerance": 0, "XSCALE": 1, "YSCALE": 1})
                self.assertFalse(reads, "graph construction read source pixels")
                self.assertTrue(out.data.__dask_graph__())
                actual = out.compute(scheduler="threads", num_workers=2)
        self.assertTrue(reads)
        # Observes actual lazy reader pixel windows, including chunk boundaries.
        for key in reads:
            self.assertGreaterEqual(key[-2].start, 128)
            self.assertLessEqual(key[-2].stop, 384)
            self.assertGreaterEqual(key[-1].start, 128)
            self.assertLessEqual(key[-1].stop, 512)
        return actual, expected, grid

    def assert_pixels_and_grid(self, actual, expected, grid):
        np.testing.assert_array_equal(np.isnan(actual.data[0]), np.isnan(expected))
        np.testing.assert_allclose(actual.data[0], expected, atol=0.01, rtol=0, equal_nan=True)
        self.assertEqual(actual.odc.geobox, grid)
        self.assertEqual(actual.rio.crs.to_epsg(), 32635)
        self.assertEqual(actual.rio.transform(), grid.transform)

    def test_lazy_continuous_warp_matches_full_source_oracle_and_cog_reopen(self):
        actual, expected, grid = self.warp()
        self.assert_pixels_and_grid(actual, expected, grid)
        path = self.root / "warped.tif"
        actual.rio.to_raster(path, driver="COG", compress="DEFLATE")
        with rio.open(path) as result:
            np.testing.assert_allclose(result.read(1), expected, atol=0.01, rtol=0, equal_nan=True)
            np.testing.assert_array_equal(result.read_masks(1) == 0, np.isnan(expected))
            self.assertEqual(result.transform, grid.transform)
            self.assertEqual(result.crs.to_epsg(), 32635)
            self.assertTrue(result.is_tiled)

    def test_nearest_preserves_classes_and_chunk_edges(self):
        actual, expected, grid = self.warp(categorical=True)
        self.assert_pixels_and_grid(actual, expected, grid)
        self.assertEqual(set(np.unique(actual.data[np.isfinite(actual.data)])), {1, 2, 3, 4})
        # Control the oracle itself: an invented class at an output chunk edge
        # and an incorrect affine transform must each be rejected.
        bad = actual.copy(deep=True)
        bad.data[0, 64, 64] = 1.5
        with self.assertRaises(AssertionError):
            self.assert_pixels_and_grid(bad, expected, grid)
        shifted = GeoBox(grid.shape, grid.transform * Affine.translation(1, 0), grid.crs)
        with self.assertRaises(AssertionError):
            self.assert_pixels_and_grid(actual, expected, shifted)

    def test_eager_source_and_outside_window_are_rejected(self):
        from dask.base import is_dask_collection
        path, _ = self.source()
        grid = GeoBox((16, 16), Affine(10, 0, 660000, 0, -10, 6470000), "EPSG:3301")
        with rx.open_rasterio(path, chunks={"x": 128, "y": 128}) as src:
            eager = src.rio.reproject("EPSG:32635")
            self.assertFalse(is_dask_collection(eager.data))
            for source, window in [(eager, (0, 16, 0, 16)), (src, (-1, 16, 0, 16))]:
                with self.assertRaises(ValueError):
                    example.reproject_aoi(source, source_window=window, destination_grid=grid,
                                          resampling="nearest", src_nodata=-9999,
                                          dst_nodata=-9999, chunks=(8, 8), warp_options={})

    def cog(self, calibrated=False):
        from rasterio.shutil import copy
        path = self.root / "raw.tif"
        count = 2 if calibrated else 1
        data = np.random.default_rng(42).integers(0, 65500, (count, 1024, 1536), dtype="uint16")
        mask = np.ones(data.shape[-2:], dtype="uint8") * 255
        mask[80:130, 120:160] = 0
        with rio.open(path, "w", driver="GTiff", width=1536, height=1024,
                      count=count, dtype="uint16", crs="EPSG:3301",
                      transform=Affine(10, 0, 660000, 0, -10, 6470000)) as dst:
            dst.write(data)
            dst.write_mask(mask)
            if calibrated:
                dst.scales = (0.25, 2.5)
                dst.offsets = (100.0, -30.0)
        cog = self.root / "image.tif"
        copy(path, cog, driver="COG", BLOCKSIZE=128, COMPRESS="DEFLATE",
             OVERVIEW_RESAMPLING="NEAREST")
        return cog

    def store(self, url):
        from datetime import timedelta
        return HTTPStore(url, client_options={"allow_http": True, "timeout": "2s"},
                         retry_config={"max_retries": 0, "retry_timeout": timedelta(seconds=2)})

    def test_http_windows_and_explicit_overview_match_rasterio_masks_and_transform(self):
        path = self.cog()
        payload = path.read_bytes()
        with range_origin({"/image.tif": payload}) as (url, requests):
            async def run():
                for overview, factor in [(None, 1), (0, 2)]:
                    window = Window(col_off=117, row_off=90, width=70, height=85)
                    arrays = [r async for r in example.cog_windows(
                        self.store(url), "image.tif", windows=[window], overview=overview)]
                    self.assertEqual(len(arrays), 1)
                    array = arrays[0].raster
                    with rio.open(path) as src:
                        w = rio.windows.Window(117 * factor, 90 * factor, 70 * factor, 85 * factor)
                        expected = src.read(window=w, out_shape=(1, 85, 70), masked=True,
                                            resampling=rio.enums.Resampling.nearest)
                        actual = array.as_masked()
                        np.testing.assert_array_equal(actual.data, expected.data)
                        np.testing.assert_array_equal(np.ma.getmaskarray(actual), np.ma.getmaskarray(expected))
                        self.assertEqual(array.crs.to_epsg(), 3301)
                        self.assertEqual(array.transform,
                                         src.window_transform(w) * Affine.scale(factor))
                        if array.mask is not None:
                            np.testing.assert_array_equal(~array.mask, np.ma.getmaskarray(expected)[0])
            asyncio.run(run())
        self.assertTrue(requests)
        self.assertLess(sum(end - start + 1 for _, start, end in requests), len(payload))

    def test_per_band_calibration_survives_base_and_overview_reads(self):
        def assert_calibration(record, expected_raw, src):
            self.assertEqual(record.scales, src.scales)
            self.assertEqual(record.offsets, src.offsets)
            raw = record.raster.as_masked()
            np.testing.assert_array_equal(raw.data, expected_raw.data)
            scales = np.array(record.scales)[:, None, None]
            offsets = np.array(record.offsets)[:, None, None]
            actual = raw.astype("float64") * scales + offsets
            expected = (expected_raw.astype("float64") * np.array(src.scales)[:, None, None]
                        + np.array(src.offsets)[:, None, None])
            np.testing.assert_array_equal(np.ma.getmaskarray(actual), np.ma.getmaskarray(expected))
            np.testing.assert_array_equal(actual.compressed(), expected.compressed())

        for calibrated in (False, True):
            path = self.cog(calibrated=calibrated)
            with range_origin({"/image.tif": path.read_bytes()}) as (url, _):
                async def run():
                    for overview, factor in ((None, 1), (0, 2)):
                        # Both levels cross the fixture's invalid-pixel patch.
                        window = Window(117 // factor, 90 // factor, 70, 85)
                        records = [r async for r in example.cog_windows(
                            self.store(url), "image.tif", windows=[window], overview=overview)]
                        with rio.open(path) as src:
                            w = rio.windows.Window(window.col_off * factor, window.row_off * factor,
                                                   window.width * factor, window.height * factor)
                            expected = src.read(window=w, out_shape=(src.count, 85, 70), masked=True,
                                                resampling=rio.enums.Resampling.nearest)
                            self.assertTrue(np.ma.getmaskarray(expected).any())
                            self.assertTrue((~np.ma.getmaskarray(expected)).any())
                            assert_calibration(records[0], expected, src)
                            if calibrated:
                                # Dropping calibration must fail the same oracle
                                # even when raw pixels and georeferencing agree.
                                lost = SimpleNamespace(raster=records[0].raster,
                                                       scales=(1.0,) * src.count,
                                                       offsets=(0.0,) * src.count)
                                with self.assertRaises(AssertionError):
                                    assert_calibration(lost, expected, src)
                asyncio.run(run())

    def test_real_reads_obey_window_concurrency_and_do_not_prefetch_unbounded_batches(self):
        from async_geotiff import GeoTIFF
        path = self.cog()
        original = GeoTIFF.read
        active = peak = calls = 0

        async def observed(image, **kwargs):
            nonlocal active, peak, calls
            active += 1
            calls += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                return await original(image, **kwargs)
            finally:
                active -= 1

        with range_origin({"/image.tif": path.read_bytes()}) as (url, _):
            async def run():
                iterator = example.cog_windows(
                    self.store(url), "image.tif", overview=None, concurrency=2,
                    windows=(Window(col_off=128 * i, row_off=0, width=16, height=16)
                             for i in range(6)))
                await anext(iterator)
                self.assertEqual(calls, 2)
                async for _ in iterator:
                    pass
            with patch.object(GeoTIFF, "read", observed):
                asyncio.run(run())
        self.assertEqual(calls, 6)
        self.assertEqual(peak, 2)
        self.assertEqual(active, 0)

    def test_invalid_window_overview_and_budget_fail(self):
        path = self.cog()
        with range_origin({"/image.tif": path.read_bytes()}) as (url, _):
            async def run():
                for window, overview, limit in [
                    (Window(0, 0, 16, 16), 99, 256),
                    (Window(0, 0, 17, 16), None, 256),
                    (Window(1500, 0, 70, 16), None, 4096),
                ]:
                    with self.assertRaises(ValueError):
                        async for _ in example.cog_windows(
                            self.store(url), "image.tif", windows=[window], overview=overview,
                            max_window_pixels=limit):
                            self.fail("invalid request produced an array")
            asyncio.run(run())

    def test_transport_failure_and_unsupported_codec_are_errors(self):
        path = self.cog()
        payload = bytearray(path.read_bytes())
        self.assertEqual(payload[:4], b'II*\x00')
        ifd = struct.unpack_from('<I', payload, 4)[0]
        count = struct.unpack_from('<H', payload, ifd)[0]
        for index in range(count):
            entry = ifd + 2 + index * 12
            if struct.unpack_from('<H', payload, entry)[0] == 259:
                struct.pack_into('<H', payload, entry + 8, 65000)  # Unsupported TIFF compression.
                break
        else:
            self.fail("fixture has no compression tag to mutate")
        with range_origin({"/failed.tif": 503, "/codec.tif": bytes(payload)}) as (url, _):
            async def run():
                for name, error, message in [('missing.tif', Exception, '404 Not Found'),
                                             ('failed.tif', Exception, '503 Service Unavailable'),
                                             ('codec.tif', ValueError, 'compression')]:
                    # async-tiff wraps transport errors in a Rust exception
                    # that is not exported by its Python module. Match the
                    # actual failure cause; AssertionError cannot satisfy it.
                    with self.subTest(name=name), self.assertRaisesRegex(error, message):
                        async for _ in example.cog_windows(
                            self.store(url), name, windows=[Window(117, 90, 70, 85)],
                            overview=None, timeout=2):
                            self.fail("failed input produced pixels")
            asyncio.run(run())

    def test_timeout_cancels_sibling_reads(self):
        from async_geotiff import GeoTIFF
        from unittest.mock import AsyncMock
        path = self.cog()
        active = calls = 0

        async def stalled(image, **kwargs):
            nonlocal active, calls
            active += 1
            calls += 1
            try:
                await asyncio.sleep(60)
            finally:
                active -= 1

        with range_origin({"/image.tif": path.read_bytes()}) as (url, _):
            async def run():
                # Separate metadata latency from the read deadline, so the
                # test cannot pass without actually starting sibling reads.
                image = await GeoTIFF.open("image.tif", store=self.store(url))
                with patch.object(GeoTIFF, 'open', AsyncMock(return_value=image)), \
                        patch.object(GeoTIFF, 'read', stalled):
                    with self.assertRaises(asyncio.TimeoutError):
                        async for _ in example.cog_windows(
                            self.store(url), "image.tif", overview=None,
                            windows=[Window(0, 0, 16, 16)] * 2, timeout=0.1):
                            self.fail("timed-out input produced pixels")
                self.assertEqual(active, 0)
                self.assertEqual(calls, 2)
            asyncio.run(run())
