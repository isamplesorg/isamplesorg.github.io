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

// Length is counted in Unicode CODE POINTS ([...t].length), not UTF-16
// units (t.length) — Python's len(str) counts code points, so astral-plane
// tokens (e.g. Deseret 𐐀, 2 UTF-16 units each) would otherwise pass the
// filter in Python and fail it here (Codex review of #329, verified).
const codePointLen = (t) => [...t].length;

export function tokenize(text) {
    if (!text) return [];
    let s = String(text).normalize('NFKC');          // 1
    s = s.toLowerCase();                              // 2
    s = s.normalize('NFD').replace(/\p{Mn}/gu, '').normalize('NFC'); // 3
    s = s.replace(/[^\p{L}\p{N}]/gu, ' ');            // 4
    return s.split(' ')                               // 5
        .filter(t => {                                // 6
            const n = codePointLen(t);
            return n >= 1 && n <= MAX_TOKEN_LEN;
        });
}
