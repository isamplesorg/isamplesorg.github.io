"""
Feature: Footer and External Links
  As a visitor on any page
  I want to see consistent footer information and working external links
  So that I can find funding info, legal notices, and related resources

  Wireframe ref: Figma frame [33:425] (footer visible on all frames)
"""
from conftest import SITE_URL


class TestFooterContent:
    """Scenario: Footer displays NSF funding acknowledgement."""

    def test_footer_has_nsf_grant_numbers(self, page):
        """Given I am on any page, Then I see NSF grant numbers in the footer."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        footer = page.locator("footer, .page-footer")
        assert footer.get_by_text("2004839").count() > 0

    def test_footer_has_copyright(self, page):
        """And the footer contains a copyright notice."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        footer = page.locator("footer, .page-footer")
        assert footer.get_by_text("Copyright").count() > 0

    def test_footer_has_disclaimer(self, page):
        """And the footer includes the NSF disclaimer."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        footer = page.locator("footer, .page-footer")
        assert footer.get_by_text("not necessarily reflect").count() > 0


class TestExternalLinks:
    """Scenario: Navbar external links point to correct destinations."""

    def test_github_icon_links_to_isamplesorg(self, page):
        """Given I am on any page, Then the GitHub icon links to isamplesorg."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        gh_link = page.locator("a[href*='github.com/isamplesorg']").first
        assert gh_link is not None
        href = gh_link.get_attribute("href")
        assert "github.com/isamplesorg" in href

    def test_slack_icon_links_to_workspace(self, page):
        """And the Slack icon links to the iSamples workspace."""
        page.goto(SITE_URL, wait_until="domcontentloaded")
        slack_link = page.locator("a[href*='isamples.slack.com']")
        assert slack_link.count() > 0


class TestMetadataModelLink:
    """Scenario: Metadata Model external link opens correctly."""

    def test_metadata_model_link_exists(self, page):
        """Given I navigate to Architecture, Then Metadata Model links to external site."""
        page.goto(f"{SITE_URL}/design/index.html", wait_until="domcontentloaded")
        link = page.locator("a[href*='isamplesorg.github.io/metadata']")
        assert link.count() > 0
