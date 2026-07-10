"""Canonical Python tokenizer for the iSamples search substrate (#169 §2, #170).

MUST stay in lockstep with the JS twin `assets/js/search_tokenizer.js`.
Both implementations are run against `tests/search_tokenizer_regression.json`
in CI; any divergence is a hard failure (SEARCH_INDEX_V1.md §2).

Pipeline (order matters, and is part of the contract):
  1. Unicode NFKC normalization (canonical + compatibility composition —
     folds full-width forms, ligatures, etc.).
  2. Lowercase.
  3. Diacritic strip: NFD decomposition, drop combining marks (Mn), then
     NFC recomposition of what's left.
  4. Replace every non-alphanumeric character with a space (punctuation
     strip — hyphens, colons, slashes, quotes all become separators, so
     `Iron-Age` → `iron age`, `IGSN:HRV000ABC` → `igsn hrv000abc`).
     "Alphanumeric" is Unicode-aware (`str.isalnum()`), so CJK, Greek,
     Cyrillic text survives.
  5. Whitespace split.
  6. Length filter: keep tokens with 1 <= len <= 64.

No stemming. No stopword removal here — stopwords are indexed at build
time and dropped at QUERY time only (SEARCH_INDEX_V1.md §3), which this
module deliberately does not implement.
"""

from __future__ import annotations

import unicodedata

MAX_TOKEN_LEN = 64


def tokenize(text: str | None) -> list[str]:
    """Tokenize one text fragment per the v1 contract. Deterministic, pure."""
    if not text:
        return []
    # 1. NFKC compatibility normalization.
    s = unicodedata.normalize("NFKC", text)
    # 2. Lowercase.
    s = s.lower()
    # 3. Diacritic strip: NFD, drop combining marks, recompose.
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = unicodedata.normalize("NFC", s)
    # 4. Non-alphanumeric -> space (Unicode-aware).
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    # 5-6. Split + length filter.
    return [t for t in s.split() if 1 <= len(t) <= MAX_TOKEN_LEN]
