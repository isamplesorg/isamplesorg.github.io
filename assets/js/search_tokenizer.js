// Canonical JS tokenizer for the iSamples search substrate (#169 §2, #170).
//
// MUST stay in lockstep with the Python twin `tools/search_tokenizer.py`.
// Both run against `tests/search_tokenizer_regression.json` in CI; any
// divergence is a hard failure (SEARCH_INDEX_V1.md §2).
//
// Pipeline (order matters, part of the contract):
//   1. NFKC normalize  2. lowercase  3. diacritic strip (NFD, drop \p{Mn},
//   NFC)  4. non-alphanumeric -> space (Unicode-aware: \p{L}\p{N} survive,
//   so `Iron-Age` -> `iron age`, `IGSN:HRV000ABC` -> `igsn hrv000abc`)
//   5. whitespace split  6. length filter 1..64.
//
// Parity note: step 4 replaces every non-alphanumeric character (including
// all exotic whitespace) with a plain space, so step 5's split semantics
// cannot diverge between Python str.split() and this implementation.
//
// No stemming; no stopword removal here (query-time policy, §3).

export const MAX_TOKEN_LEN = 64;

export function tokenize(text) {
    if (!text) return [];
    let s = String(text).normalize('NFKC');          // 1
    s = s.toLowerCase();                              // 2
    s = s.normalize('NFD').replace(/\p{Mn}/gu, '').normalize('NFC'); // 3
    s = s.replace(/[^\p{L}\p{N}]/gu, ' ');            // 4
    return s.split(' ')                               // 5
        .filter(t => t.length >= 1 && t.length <= MAX_TOKEN_LEN); // 6
}
