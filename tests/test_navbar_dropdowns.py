"""
Feature: Navbar Dropdown Menus
  As a visitor navigating iSamples
  I want dropdown menus on the navbar to reveal sub-pages
  So that I can quickly reach any section without using the sidebar

  Wireframe ref: Figma frame [33:425] Home (6-item navbar)
  Implementation: PR #103
"""
import pytest
from conftest import SITE_URL


class TestHowToUseDropdown:
    """Scenario: How to Use dropdown shows 5 sub-items."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_how_to_use_dropdown_has_overview(self, page):
        """Given I hover over How to Use, Then I see Overview."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("How to Use").hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("Overview").count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_how_to_use_dropdown_has_deep_dive(self, page):
        """And I see Deep-Dive Analysis."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("How to Use").hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("Deep-Dive Analysis").count() > 0


class TestAboutDropdown:
    """Scenario: About dropdown shows 4 sub-items."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_about_dropdown_has_objectives(self, page):
        """Given I hover over About, Then I see Objectives."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("About", exact=True).hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("Objectives").count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_about_dropdown_has_pis(self, page):
        """And I see PIs and Contributors."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("About", exact=True).hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("PIs and Contributors").count() > 0


class TestArchitectureDropdown:
    """Scenario: Architecture & Vocabularies dropdown shows sub-items."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_architecture_dropdown_has_requirements(self, page):
        """Given I hover over Architecture, Then I see Requirements."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("Architecture").hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("Requirements").count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_architecture_dropdown_has_vocabularies(self, page):
        """And I see Vocabularies."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("Architecture").hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("Vocabularies").count() > 0


class TestResearchDropdown:
    """Scenario: Research & Resources dropdown shows sub-items."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_research_dropdown_has_publications(self, page):
        """Given I hover over Research, Then I see Publications & Conferences."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("Research").hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("Publications").count() > 0

    @pytest.mark.xfail(reason="Not yet tested: #104 P0 — navbar dropdowns")
    def test_research_dropdown_has_zenodo(self, page):
        """And I see Zenodo Community."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        page.locator(".navbar").get_by_text("Research").hover()
        dropdown = page.locator(".dropdown-menu:visible")
        assert dropdown.get_by_text("Zenodo").count() > 0
