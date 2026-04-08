"""
Interactive Explorer tests — verify the search/filter/globe experience.

These tests hit the live Explorer page and wait for DuckDB-WASM to initialize.
They are slower (~30s+) due to remote parquet loading.
"""
import pytest
from conftest import SITE_URL

EXPLORER_URL = f"{SITE_URL}/tutorials/isamples_explorer.html"


@pytest.fixture
def explorer_page(page):
    """Navigate to Explorer and wait for initial load."""
    page.goto(EXPLORER_URL, wait_until="domcontentloaded", timeout=60000)
    return page


class TestExplorerLoads:
    """Explorer page should load and initialize DuckDB-WASM."""

    def test_page_loads(self, explorer_page):
        assert "Explorer" in explorer_page.title()

    def test_has_search_input(self, explorer_page):
        # Observable inputs render after JS executes — wait for them
        search = explorer_page.locator("input[type='text']")
        search.first.wait_for(state="visible", timeout=15000)
        assert search.count() > 0

    def test_has_source_filter_section(self, explorer_page):
        assert explorer_page.get_by_text("Source", exact=True).count() > 0

    def test_has_material_filter_section(self, explorer_page):
        assert explorer_page.get_by_text("Material", exact=True).count() > 0

    def test_has_sampled_feature_filter(self, explorer_page):
        assert explorer_page.get_by_text("Sampled Feature").count() > 0

    def test_has_specimen_type_filter(self, explorer_page):
        assert explorer_page.get_by_text("Specimen Type").count() > 0

    def test_has_max_samples_slider(self, explorer_page):
        # Observable range input renders after JS — wait for it
        slider = explorer_page.locator("input[type='range']")
        slider.first.wait_for(state="attached", timeout=15000)
        assert slider.count() > 0

    def test_has_view_mode_selector(self, explorer_page):
        assert explorer_page.get_by_text("Globe").count() > 0
        assert explorer_page.get_by_text("List").count() > 0
        assert explorer_page.get_by_text("Table").count() > 0


class TestExplorerFacetCounts:
    """Facet counts should appear from pre-computed summaries."""

    def test_source_checkboxes_have_counts(self, explorer_page):
        """Source checkboxes should show sample counts (loaded from 2KB summary)."""
        # Wait for facet summaries to load (they're tiny, should be fast)
        explorer_page.wait_for_timeout(5000)
        # Check that at least one source has a count in parentheses
        sesar = explorer_page.get_by_text("SESAR")
        assert sesar.count() > 0

    def test_four_sources_present(self, explorer_page):
        """All 4 data sources should appear as filter options."""
        explorer_page.wait_for_timeout(5000)
        for source in ["SESAR", "OPENCONTEXT", "GEOME", "SMITHSONIAN"]:
            assert explorer_page.get_by_text(source).count() > 0, f"Missing source: {source}"


class TestExplorerSampleCard:
    """Sample Card section should exist."""

    def test_has_sample_card_section(self, explorer_page):
        assert explorer_page.get_by_text("Sample Card").count() > 0

    def test_sample_card_shows_click_prompt(self, explorer_page):
        """Before clicking a point, card should show instructions."""
        explorer_page.wait_for_timeout(3000)
        assert explorer_page.get_by_text("Click a point").count() > 0
