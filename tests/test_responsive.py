"""
Feature: Responsive Layout
  As a visitor on a tablet or phone
  I want the site to adapt to my screen size
  So that I can read content and navigate without horizontal scrolling

  Wireframe ref: Figma frame [33:425] (implied responsive behavior)
"""
import pytest
from conftest import SITE_URL


class TestMobileNavigation:
    """Scenario: Navbar collapses to hamburger menu on small screens."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — mobile nav")
    def test_hamburger_visible_on_mobile(self, page):
        """Given I am on a 375px-wide screen, Then I see a hamburger menu button."""
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(SITE_URL, wait_until="domcontentloaded")
        toggle = page.locator(".navbar-toggler, button[aria-label='Toggle navigation']")
        assert toggle.count() > 0
        assert toggle.first.is_visible()

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — mobile nav")
    def test_sidebar_hidden_on_mobile(self, page):
        """And the sidebar is not visible on mobile."""
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(SITE_URL, wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        if sidebar.count() > 0:
            assert not sidebar.first.is_visible()


class TestTabletLayout:
    """Scenario: Content is readable at tablet width."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — tablet layout")
    def test_no_horizontal_scroll_at_768(self, page):
        """Given I am on a 768px-wide screen, Then there is no horizontal scrollbar."""
        page.set_viewport_size({"width": 768, "height": 1024})
        page.goto(SITE_URL, wait_until="domcontentloaded")
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        viewport_width = page.evaluate("document.documentElement.clientWidth")
        assert scroll_width <= viewport_width + 5, (
            f"Horizontal overflow: scrollWidth={scroll_width}, viewport={viewport_width}"
        )


class TestDesktopLayout:
    """Scenario: Full navigation visible on desktop."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — desktop layout")
    def test_navbar_expanded_on_desktop(self, page):
        """Given I am on a 1280px-wide screen, Then the navbar items are visible."""
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(SITE_URL, wait_until="domcontentloaded")
        navbar = page.locator(".navbar")
        assert navbar.get_by_text("About").first.is_visible()

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — desktop layout")
    def test_sidebar_visible_on_desktop(self, page):
        """And the sidebar is visible on inner pages."""
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        sidebar = page.locator(".sidebar-navigation")
        assert sidebar.count() > 0
        assert sidebar.first.is_visible()
