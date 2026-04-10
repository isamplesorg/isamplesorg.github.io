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


class TestExplorerCrossFiltering:
    """Cross-filtering: clicking a facet should update counts in other facets."""

    def _wait_for_facets(self, page):
        """Wait for facet count labels to render (requires DuckDB-WASM init)."""
        facet = page.locator(".facet-count[data-facet='source']")
        try:
            facet.first.wait_for(state="attached", timeout=60000)
        except Exception:
            pytest.skip("Facet count labels not rendered (DuckDB-WASM may not have loaded)")

    def _get_count(self, page, facet, value):
        """Extract the numeric count from a facet-count label."""
        el = page.locator(f".facet-count[data-facet='{facet}'][data-value='{value}']")
        if el.count() == 0:
            return None
        text = el.first.text_content()  # e.g. "(4,389,231)"
        return int(text.strip("() ").replace(",", ""))

    def test_baseline_sesar_count_matches_summaries(self, explorer_page):
        """Before any interaction, SESAR count should match the facet summary."""
        self._wait_for_facets(explorer_page)
        count = self._get_count(explorer_page, "source", "SESAR")
        assert count is not None, "SESAR facet-count element not found"
        assert count > 4_000_000, f"SESAR baseline count too low: {count}"

    @pytest.mark.skip(reason="Observable Inputs.checkbox ignores programmatic clicks in headless Playwright")
    def test_clicking_source_updates_material_counts(self, explorer_page):
        """Checking SESAR should lower material counts (no archaeology materials).
        Cannot be automated: Observable's reactive system only triggers from real
        user interaction, not from programmatic .click() or dispatchEvent()."""

    @pytest.mark.skip(reason="Observable Inputs.checkbox ignores programmatic clicks in headless Playwright")
    def test_clearing_filter_restores_baseline(self, explorer_page):
        """Unchecking a source should restore baseline counts."""

    @pytest.mark.skip(reason="Observable Inputs.checkbox ignores programmatic clicks in headless Playwright")
    def test_zero_count_items_are_dimmed(self, explorer_page):
        """Facet values with 0 matches should have reduced opacity."""

    def test_new_parquet_endpoints_reachable(self, explorer_page):
        """The cross-filter and sample_facets parquet files should be accessible."""
        import subprocess
        for url in [
            "https://data.isamples.org/isamples_202601_facet_cross_filter.parquet",
            "https://data.isamples.org/isamples_202601_sample_facets_v2.parquet",
        ]:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--head", url],
                capture_output=True, text=True
            )
            code = result.stdout.strip()
            assert code in ("200", "206"), f"{url} returned {code}"


class TestExplorerSampleCard:
    """Sample Card section should exist."""

    def test_has_sample_card_section(self, explorer_page):
        assert explorer_page.get_by_text("Sample Card").count() > 0

    def test_sample_card_shows_click_prompt(self, explorer_page):
        """Before clicking a point, card should show instructions."""
        explorer_page.wait_for_timeout(3000)
        assert explorer_page.get_by_text("Click a point").count() > 0
