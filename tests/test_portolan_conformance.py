"""Do the Portolan conventions this repo documents hold against a real catalog?

`references/data-sources.md` tells agents how to recognize and read a Portolan
catalog. That guidance is a claim about the world, and the fixture catalog in
`evals/fixtures/mini-portolan/` cannot falsify it — we wrote both, so they agree
by construction. This module checks the same claims against a published catalog
instead, and it has already earned its place: it is what showed that a
partitioned collection carries no `data` asset at all.

Opt-in. A third-party outage must never redden this repository, so the tests
skip unless `OPENMAPSTACK_NETWORK_TESTS=1`, and skip rather than fail when the
service cannot be reached. A skip here is `not_testable`, not a pass.

    OPENMAPSTACK_NETWORK_TESTS=1 python -m unittest tests.test_portolan_conformance -v
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request
from typing import Any

#: A real, published Portolan catalog. Browsable at
#: https://browser.portolan-sdi.org/#/external/data.source.coop/ftw/global-data/catalog.json
CATALOG_URL = "https://data.source.coop/ftw/global-data/catalog.json"

NETWORK_ENABLED = os.environ.get("OPENMAPSTACK_NETWORK_TESTS") == "1"

#: sha2-256 in multihash: 0x12 (function) 0x20 (32-byte digest), hex-encoded.
MULTIHASH_SHA256_PREFIX = "1220"


def _fetch(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "openmapstack-tests/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve(base_url: str, href: str) -> str:
    if href.startswith("http"):
        return href
    return base_url.rsplit("/", 1)[0] + "/" + href.lstrip("./")


def _links(document: dict, rel: str) -> list[dict]:
    return [link for link in document.get("links", []) if link.get("rel") == rel]


@unittest.skipUnless(NETWORK_ENABLED, "set OPENMAPSTACK_NETWORK_TESTS=1 to check a live catalog")
class PortolanConventionsHoldTests(unittest.TestCase):
    """Each test names the line of guidance it is checking."""

    catalog: dict
    collection: dict
    collection_url: str

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.catalog = _fetch(CATALOG_URL)
            child = _links(cls.catalog, "child")[0]
            cls.collection_url = _resolve(CATALOG_URL, child["href"])
            cls.collection = _fetch(cls.collection_url)
        except (urllib.error.URLError, TimeoutError, OSError, IndexError, ValueError) as exc:
            raise unittest.SkipTest(f"live catalog unreachable: {exc}") from exc

    def test_the_version_uri_is_how_you_recognize_one(self) -> None:
        """"`stac_extensions` carrying a schemas.portolan-sdi.org URI"."""
        extensions = self.catalog.get("stac_extensions") or []
        portolan = [uri for uri in extensions if "schemas.portolan-sdi.org/portolan/" in uri]
        self.assertTrue(portolan, f"no Portolan schema URI in {extensions}")

    def test_agent_and_human_guides_are_linked_by_rel(self) -> None:
        """"an AGENTS.md and README.md beside every catalog and collection"."""
        for document, where in ((self.catalog, "catalog"), (self.collection, "collection")):
            self.assertTrue(_links(document, "agents"), f"{where} has no rel: agents link")
            self.assertTrue(_links(document, "describedby"), f"{where} has no rel: describedby link")

    def test_the_collection_publishes_what_a_pin_needs(self) -> None:
        """The pinning table: SPDX license, providers with producer and host."""
        license_id = self.collection.get("license")
        self.assertTrue(license_id, "collection declares no license")
        if license_id == "other":
            self.assertTrue(_links(self.collection, "license"), "license 'other' needs a rel: license link")
        roles = {role for provider in self.collection.get("providers", []) for role in provider.get("roles", [])}
        self.assertIn("producer", roles)
        self.assertIn("host", roles)

    def test_data_is_reachable_by_role_or_by_partition(self) -> None:
        """The claim a real catalog corrected.

        A collection with no `data` asset is partitioned rather than empty: the
        role sits on an item, or the files are behind `partition:glob`. Guidance
        that only said "select the data role" would strand an agent here.
        """
        assets = self.collection.get("assets") or {}
        has_data_asset = any("data" in (asset.get("roles") or []) for asset in assets.values())
        partitioned = bool(self.collection.get("partition:glob")) or bool(_links(self.collection, "item"))
        self.assertTrue(
            has_data_asset or partitioned,
            "collection exposes neither a data-role asset nor a partition:glob/items to reach one",
        )
        if has_data_asset:
            return
        item = _fetch(_resolve(self.collection_url, _links(self.collection, "item")[0]["href"]))
        item_roles = {
            role for asset in (item.get("assets") or {}).values() for role in (asset.get("roles") or [])
        }
        self.assertIn("data", item_roles, "partitioned collection's item carries no data-role asset either")

    def test_file_checksum_is_multihash_not_bare_sha256(self) -> None:
        """The pinning trap: copying it into a `sha256:` field records a lie."""
        item_links = _links(self.collection, "item")
        if not item_links:
            self.skipTest("collection is not partitioned into items")
        item = _fetch(_resolve(self.collection_url, item_links[0]["href"]))
        checksums = [
            asset["file:checksum"]
            for asset in (item.get("assets") or {}).values()
            if "file:checksum" in asset
        ]
        if not checksums:
            self.skipTest("no asset on this item carries file:checksum")
        for checksum in checksums:
            self.assertTrue(
                checksum.startswith(MULTIHASH_SHA256_PREFIX),
                f"{checksum!r} is not multihash sha2-256; the reference's pinning note would be wrong",
            )
            self.assertNotEqual(len(checksum), 64, "a 64-char value would be a bare sha256, not multihash")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
