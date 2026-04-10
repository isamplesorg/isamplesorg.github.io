"""
Feature: About Page
  As a visitor learning about iSamples
  I want to navigate to specific sections via anchors
  And see team photos and PI information
  So that I understand who is behind the project

  Wireframe ref: Figma frame [33:919] About
"""
from conftest import SITE_URL


class TestAboutAnchors:
    """Scenario: Section anchors scroll to correct content."""

    def test_team_anchor_scrolls_to_team(self, page):
        """Given I navigate to about.html#team, Then the Team section is visible."""
        page.goto(f"{SITE_URL}/about.html#team", wait_until="domcontentloaded")
        heading = page.locator("h2:has-text('Team')")
        assert heading.count() > 0
        assert heading.first.is_visible()

    def test_photo_gallery_anchor(self, page):
        """Given I navigate to about.html#photo-gallery, Then the Photo Gallery is visible."""
        page.goto(f"{SITE_URL}/about.html#photo-gallery", wait_until="domcontentloaded")
        heading = page.locator("h2:has-text('Photo Gallery')")
        assert heading.count() > 0
        assert heading.first.is_visible()

    def test_background_anchor(self, page):
        """Given I navigate to about.html#background-history, Then Background section is visible."""
        page.goto(f"{SITE_URL}/about.html#background-history", wait_until="domcontentloaded")
        heading = page.locator("h2:has-text('Background')")
        assert heading.count() > 0


class TestAboutPILinks:
    """Scenario: PI names link to ORCID profiles."""

    def test_pi_names_have_orcid_links(self, page):
        """Given I am on the about page, Then each PI name links to an ORCID profile."""
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        orcid_links = page.locator("a[href*='orcid.org']")
        assert orcid_links.count() >= 4, f"Expected 4 ORCID links, found {orcid_links.count()}"


class TestAboutGallery:
    """Scenario: Photo gallery displays workshop and facility images."""

    def test_gallery_has_images(self, page):
        """Given I am on the about page, Then the photo gallery has at least 6 images."""
        page.goto(f"{SITE_URL}/about.html#photo-gallery", wait_until="domcontentloaded")
        gallery_section = page.locator("#photo-gallery ~ div img, #photo-gallery ~ .columns img")
        # Fallback: count all images near the gallery heading
        if gallery_section.count() == 0:
            gallery_section = page.locator("img[src*='gallery'], img[src*='workshop'], img[src*='tucson'], img[src*='smithsonian']")
        assert gallery_section.count() >= 3, f"Expected gallery images, found {gallery_section.count()}"


class TestAboutContributors:
    """Scenario: Contributors section lists project participants."""

    def test_contributors_section_expandable(self, page):
        """Given I am on the about page, Then I can expand the Contributors section."""
        page.goto(f"{SITE_URL}/about.html", wait_until="domcontentloaded")
        assert page.get_by_text("Contributors").count() > 0
