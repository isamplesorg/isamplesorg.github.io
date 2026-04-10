"""
Feature: Homepage
  As a visitor to iSamples.org
  I want to see an engaging overview of the project
  So that I understand what iSamples offers and can start exploring

  Wireframe ref: Figma frame [33:425] Home
"""
from conftest import SITE_URL


class TestHomepageShowcase:
    """Scenario: Showcase gallery displays real sample images."""

    def test_showcase_has_four_images(self, page):
        """Given I am on the homepage, Then I should see 4 showcase images."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        images = page.locator(".quarto-layout-cell img[data-group='showcase']")
        assert images.count() >= 4

    def test_showcase_images_have_alt_text(self, page):
        """And each showcase image should have alt text."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        images = page.locator(".quarto-layout-cell img[data-group='showcase']")
        for i in range(images.count()):
            alt = images.nth(i).get_attribute("alt")
            assert alt and len(alt) > 0, f"Image {i} missing alt text"


class TestHomepageCallouts:
    """Scenario: Collapsible callouts explain the project."""

    def test_has_what_is_isamples_callout(self, page):
        """Given I am on the homepage, Then I should see a 'What is iSamples?' callout."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        assert page.get_by_text("What is iSamples").count() > 0

    def test_has_how_can_i_access_callout(self, page):
        """And I should see a 'How can I access it?' callout."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        assert page.get_by_text("How can I access").count() > 0

    def test_has_why_browser_based_callout(self, page):
        """And I should see a 'Why browser-based?' callout."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        assert page.get_by_text("Why browser-based").count() > 0


class TestHomepageHero:
    """Scenario: Hero section draws visitors in."""

    def test_hero_shows_sample_count(self, page):
        """Given I am on the homepage, Then I should see '6.7 million' in the stats."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        assert page.get_by_text("6.7 million").count() > 0

    def test_hero_shows_repository_count(self, page):
        """And I should see '4 repositories'."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        assert page.get_by_text("4 repositories").count() > 0
