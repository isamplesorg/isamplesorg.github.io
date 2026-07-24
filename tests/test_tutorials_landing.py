"""
Feature: How to Use / Tutorials Landing
  As a new user exploring iSamples
  I want a guided overview of the available tutorials
  So that I can choose the right starting point for my skill level

  Wireframe ref: Figma frame [33:1005] How to Use
"""
from conftest import SITE_URL


HOW_TO_USE_URL = f"{SITE_URL}/how-to-use.html"


class TestHowToUseLanding:
    """Scenario: Landing page lists all tutorial pathways."""

    def test_has_guided_tour_link(self, page):
        """Given I am on the How to Use page, Then I see a link to the Guided Tour
        in the MAIN CONTENT (scoped so the permanent navbar link can't satisfy it)."""
        page.goto(HOW_TO_USE_URL, wait_until="domcontentloaded")
        link = page.locator("main a:has-text('Guided Tour')")
        assert link.count() > 0

    def test_has_globe_viz_link(self, page):
        """And I see a link to the 3D Globe Visualization."""
        page.goto(HOW_TO_USE_URL, wait_until="domcontentloaded")
        link = page.locator("a:has-text('Globe')")
        assert link.count() > 0

    def test_has_narrow_vs_wide_link(self, page):
        """And I see a link to Narrow vs Wide."""
        page.goto(HOW_TO_USE_URL, wait_until="domcontentloaded")
        link = page.locator("a:has-text('Narrow')")
        assert link.count() > 0


class TestTutorialPageLoads:
    """Scenario: Each tutorial page loads without JavaScript errors."""

    def test_guided_tour_loads(self, page):
        """Given I navigate to the Guided Tour, Then the LIVE CELLS actually render
        (waits for an Observable Plot SVG — DuckDB query + chart — not just DOM)."""
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(
            f"{SITE_URL}/tutorials/explorer_guided_tour.html",
            wait_until="domcontentloaded",
        )
        # The source-counts chart is the first Plot output; its appearance proves
        # OJS booted, DuckDB-WASM initialized, and a remote parquet query ran.
        page.wait_for_selector("figure svg, svg.plot-d6a7b5", timeout=90_000)
        assert page.title() != ""
        # Allow known non-critical errors but flag unexpected ones
        critical = [e for e in errors if "TypeError" in e or "ReferenceError" in e]
        assert len(critical) == 0, f"JS errors: {critical}"

    def test_globe_viz_loads(self, page):
        """Given I navigate to /explorer.html, Then the Cesium container exists."""
        page.goto(
            f"{SITE_URL}/explorer.html",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        cesium = page.locator("#cesiumContainer, .cesium-viewer")
        assert cesium.count() > 0
