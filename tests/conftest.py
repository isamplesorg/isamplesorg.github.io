"""
Shared fixtures for iSamples website BDD tests.

Usage:
    # Against live site (default):
    pytest tests/

    # Against local Quarto preview:
    ISAMPLES_BASE_URL=http://localhost:5860 pytest tests/

    # With visible browser:
    pytest tests/ --headed
"""
import os
import pytest
from playwright.sync_api import sync_playwright


SITE_URL = os.environ.get("ISAMPLES_BASE_URL", "https://isamples.org")


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless="--headed" not in " ".join(os.sys.argv),
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="session")
def site_url():
    return SITE_URL
