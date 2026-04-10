"""
Feature: Navbar Dropdown Menus
  As a visitor navigating iSamples
  I want dropdown menus on the navbar to reveal sub-pages
  So that I can quickly reach any section without using the sidebar

  Wireframe ref: Figma frame [33:425] Home (6-item navbar)
  Implementation: PR #103
"""
from conftest import SITE_URL


def _open_dropdown(page, label, exact=False):
    """Click a Bootstrap 5 navbar dropdown toggle to reveal its menu."""
    # Structure: li.nav-item.dropdown > a.dropdown-toggle > span.menu-text
    dropdown_li = page.locator(f".navbar li.dropdown:has(a:has-text('{label}'))")
    dropdown_li.locator("a.dropdown-toggle").click()
    menu = dropdown_li.locator("ul.dropdown-menu")
    menu.wait_for(state="visible", timeout=3000)
    return menu


class TestHowToUseDropdown:
    """Scenario: How to Use dropdown shows 5 sub-items."""

    def test_how_to_use_dropdown_has_overview(self, page):
        """Given I click How to Use, Then I see Overview."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "How to Use")
        assert menu.get_by_text("Overview").count() > 0

    def test_how_to_use_dropdown_has_deep_dive(self, page):
        """And I see Deep-Dive Analysis."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "How to Use")
        assert menu.get_by_text("Deep-Dive Analysis").count() > 0


class TestAboutDropdown:
    """Scenario: About dropdown shows 4 sub-items."""

    def test_about_dropdown_has_objectives(self, page):
        """Given I click About, Then I see Objectives."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "About", exact=True)
        assert menu.get_by_text("Objectives").count() > 0

    def test_about_dropdown_has_pis(self, page):
        """And I see PIs and Contributors."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "About", exact=True)
        assert menu.get_by_text("PIs and Contributors").count() > 0


class TestArchitectureDropdown:
    """Scenario: Architecture & Vocabularies dropdown shows sub-items."""

    def test_architecture_dropdown_has_requirements(self, page):
        """Given I click Architecture, Then I see Requirements."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "Architecture")
        assert menu.get_by_text("Requirements").count() > 0

    def test_architecture_dropdown_has_vocabularies(self, page):
        """And I see Vocabularies."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "Architecture")
        assert menu.get_by_text("Vocabularies").count() > 0


class TestResearchDropdown:
    """Scenario: Research & Resources dropdown shows sub-items."""

    def test_research_dropdown_has_publications(self, page):
        """Given I click Research, Then I see Publications & Conferences."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "Research")
        assert menu.get_by_text("Publications").count() > 0

    def test_research_dropdown_has_zenodo(self, page):
        """And I see Zenodo Community."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        menu = _open_dropdown(page, "Research")
        assert menu.get_by_text("Zenodo").count() > 0
