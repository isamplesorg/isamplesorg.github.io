// Browser-side query engine for the v1 search substrate (#171, SEARCH_INDEX_V1.md).
//
// PURE functions only — no DuckDB, no fetch, no DOM. The explorer's flag
// path (Phase B) feeds this module rows it fetched via db.query; that split
// keeps every piece of query logic unit-testable in Node
// (tests/unit/search-substrate.test.mjs) and the explorer wiring thin.
//
// Pipeline (contract §3, §5):
//   tokenize (search_tokenizer.js) → drop query-time stopwords → locate each
//   token's shard file(s) → BM25 per (pid, field) posting → field-weighted
//   sum per pid → AND across tokens → top-K.

import { tokenize } from './search_tokenizer.js';

// FNV-1a 32-bit over UTF-8 bytes. MUST match tools/build_search_index.py's
// fnv1a32 exactly — parity is pinned by tests/search_fnv1a_regression.json
// (values generated from the Python implementation).
export function fnv1a32(str) {
    let h = 0x811c9dc5;
    const bytes = new TextEncoder().encode(str);
    for (const b of bytes) {
        h ^= b;
        // 32-bit multiply by the FNV prime 0x01000193 without BigInt:
        // h * 16777619 = h*2^24 + h*2^9 + h*2^8 + h*2^7 + h*2^4 + h*2 + h
        h = (h + (h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24)) >>> 0;
    }
    return h >>> 0;
}

// Curated query-time stopword list (contract §3). Build-time indexes
// EVERYTHING; dropping happens here only, so the policy stays reversible.
export const QUERY_STOPWORDS = new Set([
    'a', 'an', 'the', 'of', 'from', 'for', 'to', 'in', 'on', 'at',
    'is', 'was', 'with', 'and', 'or',
]);

// Field weights (contract §5) + BM25 constants.
export const FIELD_WEIGHTS = {
    'sample.label': 3.0,
    'concept.label': 2.5,
    'sample.place_name': 2.0,
    'sample.description': 1.0,
};
export const BM25_K1 = 1.2;
export const BM25_B = 0.75;
export const TOP_K = 50;

/**
 * Plan a query: tokenize, apply stopword policy, dedupe, and resolve the
 * substrate file path(s) for each surviving token.
 *
 * @param term        raw user input
 * @param manifest    { shardCount, hotTokens } — shardCount from
 *                    build_stats.json; hotTokens = the `tokens` object of
 *                    hot_tokens.json ({token: {key, sub_files}}).
 * @returns {{
 *   tokens: string[],          // surviving, deduped, order-preserved
 *   allStopwords: boolean,     // input had tokens but none survived (§3
 *                              //   controlled-empty state, NOT a search)
 *   empty: boolean,            // input produced no tokens at all
 *   files: string[],           // deduped relative substrate paths to fetch
 *   filesByToken: Map<string, string[]>,
 * }}
 */
export function planQuery(term, manifest) {
    const raw = tokenize(term);
    const survivors = [];
    for (const t of raw) {
        if (QUERY_STOPWORDS.has(t)) continue;
        if (!survivors.includes(t)) survivors.push(t);  // duplicate-term dedup
    }
    const filesByToken = new Map();
    const files = [];
    for (const t of survivors) {
        const hot = manifest.hotTokens && manifest.hotTokens[t];
        const tokenFiles = hot
            ? Array.from({ length: hot.sub_files },
                         (_, m) => `hot/${hot.key}_p${m}.parquet`)
            : [`shard_${String(fnv1a32(t) % manifest.shardCount).padStart(3, '0')}.parquet`];
        filesByToken.set(t, tokenFiles);
        for (const f of tokenFiles) if (!files.includes(f)) files.push(f);
    }
    return {
        tokens: survivors,
        allStopwords: raw.length > 0 && survivors.length === 0,
        empty: raw.length === 0,
        files,
        filesByToken,
    };
}

/**
 * BM25 contribution of one posting row (contract §5).
 * @param row     { field, tf, doc_len, df }
 * @param stats   { totalDocs, avgDocLen } — corpus-level; #171 Phase B reads
 *                totalDocs as the df.parquet row-domain (COUNT of (pid,field)
 *                docs) and avgDocLen over the fetched postings' universe.
 */
export function bm25Contribution(row, stats) {
    const idf = Math.log((stats.totalDocs - row.df + 0.5) / (row.df + 0.5) + 1);
    const norm = row.tf * (BM25_K1 + 1)
        / (row.tf + BM25_K1 * (1 - BM25_B + BM25_B * row.doc_len / stats.avgDocLen));
    const weight = FIELD_WEIGHTS[row.field] ?? 1.0;
    return weight * idf * norm;
}

/**
 * Combine postings into the final AND-ranked top-K.
 *
 * @param postingsByToken  Map<token, Array<{pid, field, tf, doc_len, df}>>
 * @param stats            { totalDocs, avgDocLen }
 * @param k                top-K cap (default contract TOP_K = 50)
 * @returns Array<{pid, score}> sorted score desc, pid asc for stable ties.
 */
export function combineAndRank(postingsByToken, stats, k = TOP_K) {
    const scores = new Map();   // pid -> summed score
    const matched = new Map();  // pid -> Set<token>
    for (const [token, rows] of postingsByToken) {
        for (const row of rows) {
            scores.set(row.pid, (scores.get(row.pid) ?? 0) + bm25Contribution(row, stats));
            if (!matched.has(row.pid)) matched.set(row.pid, new Set());
            matched.get(row.pid).add(token);
        }
    }
    const need = postingsByToken.size;   // AND semantics: every token matches
    const out = [];
    for (const [pid, tokens] of matched) {
        if (tokens.size === need) out.push({ pid, score: scores.get(pid) });
    }
    out.sort((a, b) => (b.score - a.score) || (a.pid < b.pid ? -1 : 1));
    return out.slice(0, k);
}
