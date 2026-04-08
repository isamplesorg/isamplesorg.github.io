"""
Requirements page tests — verify accordion behavior from PR #90.

The Requirements page has 18 collapsible callout sections that should
load collapsed and expand on click.
"""
import pytest
from conftest import SITE_URL

REQUIREMENTS_URL = f"{SITE_URL}/design/requirements.html"


class TestRequirementsAccordions:
    """All 18 requirements should be collapsible callouts."""

    def test_page_loads(self, page):
        response = page.goto(REQUIREMENTS_URL, wait_until="domcontentloaded")
        assert response.status == 200

    def test_has_18_callout_sections(self, page):
        page.goto(REQUIREMENTS_URL, wait_until="domcontentloaded")
        callouts = page.locator(".callout-note")
        assert callouts.count() == 18

    def test_callouts_are_collapsed_by_default(self, page):
        page.goto(REQUIREMENTS_URL, wait_until="domcontentloaded")
        # Quarto puts "callout-collapse collapse" on the contents div
        collapsed = page.locator(".callout-collapse.collapse")
        assert collapsed.count() == 18

    def test_clicking_callout_expands_it(self, page):
        page.goto(REQUIREMENTS_URL, wait_until="domcontentloaded")
        # Click the first callout header
        first_header = page.locator(".callout-note .callout-header").first
        first_header.click()
        # After clicking, the callout body should be visible
        first_body = page.locator(".callout-note .callout-body-container").first
        first_body.wait_for(state="visible", timeout=3000)
        assert first_body.is_visible()

    def test_first_requirement_is_mint_identifiers(self, page):
        page.goto(REQUIREMENTS_URL, wait_until="domcontentloaded")
        first_header = page.locator(".callout-note .callout-header").first
        assert "Mint Identifiers" in first_header.text_content()

    def test_last_requirement_is_validation(self, page):
        page.goto(REQUIREMENTS_URL, wait_until="domcontentloaded")
        last_header = page.locator(".callout-note .callout-header").last
        assert "Validation" in last_header.text_content()

    def test_has_intro_text(self, page):
        page.goto(REQUIREMENTS_URL, wait_until="domcontentloaded")
        assert page.get_by_text("Click any requirement to expand").count() > 0
