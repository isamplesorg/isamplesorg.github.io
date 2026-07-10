"""Python tokenizer vs the shared regression set (#170).

Scope: tokenizer ONLY (SEARCH_INDEX_V1.md §2). URI dereferencing is proved
separately in tests/test_search_index_builder.py. The JS twin runs the same
JSON in tests/unit/search-tokenizer.test.mjs; CI failing either one is the
Python↔JS parity gate.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from search_tokenizer import tokenize  # noqa: E402

REGRESSION = json.loads((REPO / "tests" / "search_tokenizer_regression.json").read_text())


@pytest.mark.parametrize(
    "entry", REGRESSION, ids=[repr(e["input"])[:40] for e in REGRESSION]
)
def test_regression_entry(entry):
    assert tokenize(entry["input"]) == entry["expected_tokens"]


def test_regression_set_is_big_enough():
    # Contract: >= 30 strings (#170 §3).
    assert len(REGRESSION) >= 30


def test_none_and_empty():
    assert tokenize(None) == []
    assert tokenize("") == []


def test_length_filter_boundaries():
    assert tokenize("x" * 64) == ["x" * 64]
    assert tokenize("x" * 65) == []
