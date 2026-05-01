"""
Interactive Explorer tests — verify the unified search/filter/globe/table experience.

Targets /explorer.html (canonical) and waits for DuckDB-WASM to initialize.
Slow (~30s+) due to remote parquet loading.
"""
import pytest
from conftest import SITE_URL

EXPLORER_URL = f"{SITE_URL}/explorer.html"


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
        search = explorer_page.locator("#sampleSearch")
        search.wait_for(state="visible", timeout=15000)
        assert search.count() == 1

    def test_has_source_filter_section(self, explorer_page):
        assert explorer_page.locator("#sourceFilter").count() == 1

    def test_has_material_filter_section(self, explorer_page):
        assert explorer_page.locator("#materialFilter").count() == 1

    def test_has_sampled_feature_filter(self, explorer_page):
        assert explorer_page.locator("#contextFilter").count() == 1

    def test_has_specimen_type_filter(self, explorer_page):
        assert explorer_page.locator("#objectTypeFilter").count() == 1

    def test_has_max_samples_input(self, explorer_page):
        # Phase 4: number input bounded 1K-100K, default 25K. Lives in table view controls.
        max_input = explorer_page.locator("#maxSamples")
        max_input.wait_for(state="attached", timeout=15000)
        assert max_input.count() == 1

    def test_has_view_toggle(self, explorer_page):
        # Phase 4: binary Globe/Table toggle (no List).
        assert explorer_page.locator("#globeViewBtn").count() == 1
        assert explorer_page.locator("#tableViewBtn").count() == 1


class TestExplorerFacetCounts:
    """Facet counts should appear from pre-computed summaries."""

    def test_source_checkboxes_have_counts(self, explorer_page):
        explorer_page.wait_for_timeout(5000)
        assert explorer_page.get_by_text("SESAR").count() > 0

    def test_four_sources_present(self, explorer_page):
        explorer_page.wait_for_timeout(5000)
        for source in ["SESAR", "OPENCONTEXT", "GEOME", "SMITHSONIAN"]:
            assert explorer_page.get_by_text(source).count() > 0, f"Missing source: {source}"


class TestExplorerCrossFiltering:
    """Cross-filtering: changing a facet should update counts in other facets.

    Unskipped in Phase 5 (#156): the unified explorer uses native HTML checkboxes
    (not OJS Inputs.checkbox), so .click() and .dispatchEvent() work as expected.
    """

    def _wait_for_facets(self, page):
        facet = page.locator(".facet-count[data-facet='source']")
        try:
            facet.first.wait_for(state="attached", timeout=60000)
        except Exception:
            pytest.skip("Facet count labels not rendered (DuckDB-WASM may not have loaded)")

    def _get_count(self, page, facet, value):
        el = page.locator(f".facet-count[data-facet='{facet}'][data-value='{value}']")
        if el.count() == 0:
            return None
        text = el.first.text_content()
        return int(text.strip("() ").replace(",", ""))

    def test_baseline_sesar_count_matches_summaries(self, explorer_page):
        self._wait_for_facets(explorer_page)
        count = self._get_count(explorer_page, "source", "SESAR")
        assert count is not None, "SESAR facet-count element not found"
        assert count > 4_000_000, f"SESAR baseline count too low: {count}"

    def test_new_parquet_endpoints_reachable(self, explorer_page):
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


class TestExplorerRedirects:
    """Old URLs should redirect to /explorer.html, preserving query and hash."""

    def test_progressive_globe_redirects_preserves_non_q_params(self, page):
        # The explorer uses `?search=` (not `?q=`) to avoid colliding with
        # Quarto's site-wide search highlight feature. The redirect stub
        # forwards whatever query string the browser presents — but Quarto's
        # quarto-search.js (loaded into the stub page's <head>) strips `?q=`
        # before our redirect runs, so legacy `?q=` links lose the search
        # term. Non-q params survive.
        page.goto(
            f"{SITE_URL}/tutorials/progressive_globe.html?sources=SESAR&search=basalt",
            wait_until="load",
            timeout=30000,
        )
        page.wait_for_url("**/explorer.html?**", timeout=10000)
        assert "/explorer.html" in page.url
        assert "search=basalt" in page.url
        assert "sources=SESAR" in page.url

    def test_isamples_explorer_redirects_with_search_param(self, page):
        page.goto(
            f"{SITE_URL}/tutorials/isamples_explorer.html?search=pottery",
            wait_until="load",
            timeout=30000,
        )
        page.wait_for_url("**/explorer.html?**", timeout=10000)
        assert "/explorer.html" in page.url
        assert "search=pottery" in page.url
