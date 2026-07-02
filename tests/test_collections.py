"""
Feature: Collections (issue #243)
  As someone exploring iSamples
  I want to jump to a named collection (e.g. an OpenContext project) and
  filter the explorer to exactly its samples
  So that I can browse meaningful groupings, not just map locations.

These tests validate the static markup the feature ships: the Collections
landing page and the explorer's `collection` facet DOM. They do NOT require the
collections.parquet / sample_collections.parquet files to be live on R2 — the
data-layer behavior is verified separately (see scripts/build_collections.py and
the data-contract checks). Run the live facet verification after those two files
are uploaded to data.isamples.org.
"""
from conftest import SITE_URL

COLLECTIONS_URL = f"{SITE_URL}/collections.html"
EXPLORER_URL = f"{SITE_URL}/explorer.html"

# Stable id for PKAP Survey Area = substr(md5('OPENCONTEXT\x1fPKAP Survey Area'), 1, 16)
PKAP_COLLECTION_ID = "dd74c71982da0e21"


class TestCollectionsPage:
    """Scenario: the Collections landing page lists featured collections."""

    def test_page_renders(self, page):
        page.goto(COLLECTIONS_URL, wait_until="domcontentloaded")
        assert page.get_by_text("Featured Collections").count() > 0

    def test_lists_pkap(self, page):
        page.goto(COLLECTIONS_URL, wait_until="domcontentloaded")
        assert page.get_by_text("PKAP", exact=False).count() > 0

    def test_presets_use_collection_param(self, page):
        """Each preset links into the explorer with a ?collection=<id> filter."""
        page.goto(COLLECTIONS_URL, wait_until="domcontentloaded")
        links = page.locator("a[href*='explorer.html?collection=']")
        assert links.count() >= 12

    def test_pkap_preset_id(self, page):
        page.goto(COLLECTIONS_URL, wait_until="domcontentloaded")
        assert page.locator(
            f"a[href*='collection={PKAP_COLLECTION_ID}']"
        ).count() >= 1


class TestExplorerCollectionFacet:
    """Scenario: the explorer exposes a Collection facet (search + checkboxes)."""

    def test_collection_filter_section_present(self, page):
        page.goto(EXPLORER_URL, wait_until="domcontentloaded")
        assert page.locator("#collectionFilter").count() == 1

    def test_collection_search_box_present(self, page):
        page.goto(EXPLORER_URL, wait_until="domcontentloaded")
        assert page.locator("#collectionSearch").count() == 1

    def test_collection_body_present(self, page):
        page.goto(EXPLORER_URL, wait_until="domcontentloaded")
        assert page.locator("#collectionFilterBody").count() == 1
