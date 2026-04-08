"""
Navigation structure tests — verify sidebar and navbar match the April 2026 wireframe.

These tests verify the structural changes from PRs #89 (nav restructure)
and #90 (accordion menus).
"""
import pytest
from conftest import SITE_URL


class TestSidebarSections:
    """Sidebar should show the wireframe's section names."""

    def test_sidebar_shows_architecture_and_vocabularies(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Architecture and Vocabularies").count() > 0

    def test_sidebar_does_not_show_old_information_architecture(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Information Architecture").count() == 0

    def test_sidebar_shows_research_and_resources(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Research & Resources").count() > 0

    def test_sidebar_does_not_show_separate_published_research(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Published Research", exact=True).count() == 0

    def test_sidebar_does_not_show_separate_resources(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        # "Resources" alone shouldn't appear as a section header
        # (it's OK inside "Research & Resources")
        sections = sidebar.locator(".sidebar-section .sidebar-section-header")
        texts = [s.text_content().strip() for s in sections.all()]
        assert "Resources" not in texts


class TestSidebarHowToUse:
    """How to Use section should have 5 sub-items matching wireframe."""

    def test_how_to_use_has_overview(self, page):
        page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Overview", exact=True).count() > 0

    def test_how_to_use_has_deep_dive(self, page):
        page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Deep-Dive Analysis").count() > 0

    def test_how_to_use_has_globe_viz(self, page):
        page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("3D Globe Visualization").count() > 0

    def test_how_to_use_has_search_explorer(self, page):
        page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Search Explorer").count() > 0

    def test_how_to_use_has_narrow_vs_wide(self, page):
        page.goto(f"{SITE_URL}/how-to-use.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Technical: Narrow vs Wide").count() > 0


class TestSidebarAbout:
    """About section should have 4 items matching wireframe."""

    def test_about_has_objectives(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Objectives", exact=True).count() > 0

    def test_about_has_pis_and_contributors(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("PIs and Contributors").count() > 0

    def test_about_has_photo_gallery(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Photo Gallery").count() > 0

    def test_about_has_background_history(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Background & History").count() > 0


class TestSidebarResearchResources:
    """Research & Resources should have 3 items matching wireframe."""

    def test_has_publications_and_conferences(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Publications & Conferences").count() > 0

    def test_has_zenodo_community(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Zenodo Community").count() > 0

    def test_has_github_repositories(self, page):
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.get_by_text("Github Repositories").count() > 0


class TestNavbar:
    """Top navbar should have the 4 main items."""

    def test_navbar_has_home(self, page):
        page.goto(SITE_URL, wait_until="domcontentloaded")
        navbar = page.locator(".navbar")
        assert navbar.get_by_text("Home", exact=True).count() > 0

    def test_navbar_has_interactive_explorer(self, page):
        page.goto(SITE_URL, wait_until="domcontentloaded")
        navbar = page.locator(".navbar")
        assert navbar.get_by_text("Interactive Explorer").count() > 0

    def test_navbar_has_how_to_use(self, page):
        page.goto(SITE_URL, wait_until="domcontentloaded")
        navbar = page.locator(".navbar")
        assert navbar.get_by_text("How to Use").count() > 0

    def test_navbar_has_about(self, page):
        page.goto(SITE_URL, wait_until="domcontentloaded")
        navbar = page.locator(".navbar")
        assert navbar.get_by_text("About", exact=True).count() > 0
