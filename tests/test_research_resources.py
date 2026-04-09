"""
Feature: Research & Resources Page
  As a researcher interested in iSamples outputs
  I want to find publications, datasets, and source code in one place
  So that I can cite the project and build on its work

  Wireframe ref: Figma frame [130:1156] Research & Resources
"""
import pytest
from conftest import SITE_URL


PUBS_URL = f"{SITE_URL}/pubs.html"


class TestResearchPageSections:
    """Scenario: All research sections appear on the unified page."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — unified research page")
    def test_has_publications_section(self, page):
        """Given I am on the research page, Then I see a Publications section."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        assert page.locator("h2:has-text('Publications')").count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — unified research page")
    def test_has_zenodo_section(self, page):
        """And I see a Zenodo Community section."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        assert page.locator("h2:has-text('Zenodo')").count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — unified research page")
    def test_has_github_section(self, page):
        """And I see a GitHub Repositories section."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        assert page.locator("h2:has-text('GitHub')").count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — unified research page")
    def test_github_table_has_repos(self, page):
        """And the GitHub section lists repository links."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        repo_links = page.locator("a[href*='github.com/isamplesorg']")
        assert repo_links.count() >= 3


class TestResearchMediaEmbeds:
    """Scenario: Conference presentations are watchable and downloadable."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — media embeds")
    def test_youtube_embed_is_responsive(self, page):
        """Given I am on the research page, Then the YouTube embed has width/height."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        iframe = page.locator("iframe[src*='youtube']")
        assert iframe.count() > 0
        box = iframe.first.bounding_box()
        assert box and box["width"] > 200

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — media embeds")
    def test_pdf_embed_loads(self, page):
        """And the PDF slides embed is present."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        pdf = page.locator("embed[type='application/pdf']")
        assert pdf.count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — media embeds")
    def test_pdf_download_link(self, page):
        """And a download link for the PDF slides exists."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        download = page.locator("a[href*='.pdf']:has-text('Download')")
        assert download.count() > 0


class TestResearchBibliography:
    """Scenario: Publications section renders bibliography entries."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — bibliography")
    def test_bibliography_has_entries(self, page):
        """Given I am on the research page, Then I see at least one citation."""
        page.goto(PUBS_URL, wait_until="domcontentloaded")
        refs = page.locator("#refs .csl-entry, .references .csl-entry")
        assert refs.count() > 0
