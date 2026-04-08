"""
Key page smoke tests — verify all important pages load and have expected content.

These catch broken pages, missing assets, and regressions in page structure.
"""
import pytest
from conftest import SITE_URL


class TestHomepage:
    """Homepage should load with hero, globe animation, and showcase."""

    def test_homepage_loads(self, page):
        response = page.goto(SITE_URL, wait_until="domcontentloaded")
        assert response.status == 200

    def test_homepage_has_title(self, page):
        page.goto(SITE_URL, wait_until="domcontentloaded")
        assert "iSamples" in page.title()

    def test_homepage_has_hero_text(self, page):
        page.goto(SITE_URL, wait_until="domcontentloaded")
        assert page.get_by_text("Internet of Samples").count() > 0

    def test_homepage_has_globe_animation(self, page):
        page.goto(SITE_URL, wait_until="domcontentloaded")
        globe = page.locator("img[src*='isamples_globe']")
        assert globe.count() > 0


class TestAboutPage:
    """About page should have all 4 wireframe sections."""

    def test_about_loads(self, page):
        response = page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        assert response.status == 200

    def test_has_objectives(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        assert page.locator("h2:has-text('Objectives')").count() > 0

    def test_has_team(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        assert page.locator("h2:has-text('Team')").count() > 0

    def test_has_photo_gallery(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        assert page.locator("h2:has-text('Photo Gallery')").count() > 0

    def test_has_background_history(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        assert page.locator("h2:has-text('Background')").count() > 0

    def test_has_pi_names(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        for name in ["Kerstin Lehnert", "Andrea Thomer", "Neil Davies", "David Vieglais"]:
            assert page.get_by_text(name).count() > 0, f"Missing PI: {name}"


class TestHowToUsePage:
    """How to Use page should have quick start and data tables."""

    def test_how_to_use_loads(self, page):
        response = page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        assert response.status == 200

    def test_has_quick_start(self, page):
        page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        assert page.get_by_text("Quick Start").count() > 0

    def test_has_data_sources_table(self, page):
        page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        assert page.get_by_text("SESAR").count() > 0
        assert page.get_by_text("OpenContext").count() > 0


class TestArchitecturePage:
    """Architecture overview should have structured sections."""

    def test_architecture_loads(self, page):
        response = page.goto(f"{SITE_URL}/design/index.html", wait_until="domcontentloaded")
        assert response.status == 200

    def test_has_core_principles(self, page):
        page.goto(f"{SITE_URL}/design/index.html", wait_until="domcontentloaded")
        assert page.get_by_text("Core Principles").count() > 0

    def test_has_link_to_requirements(self, page):
        page.goto(f"{SITE_URL}/design/index.html", wait_until="domcontentloaded")
        assert page.locator("a[href*='requirements']").count() > 0

    def test_has_link_to_metadata_model(self, page):
        page.goto(f"{SITE_URL}/design/index.html", wait_until="domcontentloaded")
        assert page.locator("a[href*='metadata']").count() > 0


class TestPublicationsPage:
    """Publications page should have presentations and bibliography."""

    def test_publications_loads(self, page):
        response = page.goto(f"{SITE_URL}/pubs.html", wait_until="domcontentloaded")
        assert response.status == 200

    def test_has_presentations_section(self, page):
        page.goto(f"{SITE_URL}/pubs.html", wait_until="domcontentloaded")
        assert page.get_by_text("Presentations").count() > 0

    def test_has_spnhc_talk_embed(self, page):
        page.goto(f"{SITE_URL}/pubs.html", wait_until="domcontentloaded")
        # Quarto {{< video >}} renders as iframe, not <a> link
        youtube = page.locator("iframe[src*='youtube']")
        assert youtube.count() > 0


class TestDataEndpoint:
    """data.isamples.org should serve parquet files with range requests."""

    def test_facet_summaries_accessible(self, page):
        # Use Playwright's API request context (not page.goto which triggers download)
        response = page.request.head(
            "https://data.isamples.org/isamples_202601_facet_summaries.parquet"
        )
        assert response.status in (200, 206)

    def test_wide_parquet_supports_range_requests(self, page):
        response = page.request.head(
            "https://data.isamples.org/isamples_202601_wide.parquet"
        )
        assert response.status in (200, 206)
        assert "bytes" in response.headers.get("accept-ranges", "")
