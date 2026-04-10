"""
Feature: Vocabularies Page
  As a data modeler or repository implementer
  I want to browse iSamples controlled vocabularies
  So that I can understand and apply the classification schemes

  Wireframe ref: Figma frame [130:1300] Architecture & Vocabularies
"""
import pytest
from conftest import SITE_URL


VOCAB_URL = f"{SITE_URL}/models/index.html"


class TestVocabularyIndex:
    """Scenario: Vocabulary index lists all SKOS vocabularies."""

    def test_has_material_type_vocab(self, page):
        """Given I am on the vocabularies page, Then I see Material Type."""
        page.goto(VOCAB_URL, wait_until="domcontentloaded")
        assert page.get_by_text("Material Type").count() > 0

    def test_has_specimen_type_vocab(self, page):
        """Given I am on the vocabularies page, Then I see Specimen Type."""
        page.goto(VOCAB_URL, wait_until="domcontentloaded")
        assert page.get_by_text("Specimen Type").count() > 0

    def test_has_sampled_feature_vocab(self, page):
        """Given I am on the vocabularies page, Then I see Sampled Feature."""
        page.goto(VOCAB_URL, wait_until="domcontentloaded")
        assert page.get_by_text("Sampled Feature").count() > 0

    def test_vocabulary_links_resolve(self, page):
        """And each vocabulary name links to its detail page."""
        page.goto(VOCAB_URL, wait_until="domcontentloaded")
        vocab_links = page.locator("a[href*='models/']")
        assert vocab_links.count() >= 3


class TestVocabularyDetail:
    """Scenario: Individual vocabulary pages show concept hierarchy."""

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — vocabulary detail page")
    def test_material_type_has_hierarchy(self, page):
        """Given I navigate to a vocabulary detail page, Then I see a concept tree."""
        page.goto(f"{SITE_URL}/models/materialType.html", wait_until="domcontentloaded")
        # SKOS concepts should render as nested lists or tree
        concepts = page.locator("li a, .concept-label")
        assert concepts.count() >= 5

    @pytest.mark.xfail(reason="Not yet tested: #104 P1 — vocabulary definitions")
    def test_concepts_have_definitions(self, page):
        """And each concept should have a definition or description."""
        page.goto(f"{SITE_URL}/models/materialType.html", wait_until="domcontentloaded")
        definitions = page.locator("dd, .concept-definition, blockquote")
        assert definitions.count() >= 3
