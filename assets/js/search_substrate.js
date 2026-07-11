// Browser-side query engine for the v1 search substrate (#171, SEARCH_INDEX_V1.md).
//
// PURE functions only — no DuckDB, no fetch, no DOM. The explorer's flag
// path feeds this module data it fetched via db.query; the split keeps every
// piece of query logic unit-testable in Node
// (tests/unit/search-substrate.test.mjs) and the explorer wiring thin.
//
// Pipeline (contract §3, §5, §6 two-tier rule):
//   tokenize (search_tokenizer.js) → drop query-time stopwords → dedupe →
//   two-tier hot policy (fetchable hot joins the AND; non-fetchable common
//   terms are dropped-with-disclosure, or an all-common query serves from
//   the hot_topk sidecar) → resolve substrate files → BM25 per posting →
//   field-weighted per-pid sums → AND across tokens → top-K.

import { tokenize } from './search_tokenizer.js';

// FNV-1a 32-bit over UTF-8 bytes. MUST match tools/build_search_index.py's
// fnv1a32 exactly — parity pinned by tests/search_fnv1a_regression.json
// (values generated from the Python implementation).
export function fnv1a32(str) {
    let h = 0x811c9dc5;
    const bytes = new TextEncoder().encode(str);
    for (const b of bytes) {
        h ^= b;
        // 32-bit multiply by the FNV prime 0x01000193 without BigInt:
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

const shardFile = (token, shardCount) =>
    `shard_${String(fnv1a32(token) % shardCount).padStart(3, '0')}.parquet`;

/**
 * Plan a query under the §6 two-tier hot rule.
 *
 * @param term       raw user input
 * @param manifest   { shardCount, hotTokens } — shardCount from
 *                   build_stats.json; hotTokens = hot_tokens.json's `tokens`
 *                   ({token: {key, sub_files, postings, total_bytes,
 *                   fetchable}}).
 * @param shardSizes optional shard_sizes.json object ({file: bytes}); when
 *                   given, the plan carries expectedBytes so callers can
 *                   report transfer up-front (§7).
 * @returns {{
 *   mode: 'empty'|'allStopwords'|'normal'|'topk',
 *   tokens: string[],          // tokens participating in the AND
 *   ignoredCommon: string[],   // non-fetchable hot terms dropped (§3 —
 *                              //   the UI MUST disclose these)
 *   files: string[],           // deduped relative substrate paths to fetch
 *   filesByToken: Map<string, string[]>,
 *   expectedBytes: number|null,
 * }}
 */
export function planQuery(term, manifest, shardSizes = null) {
    const raw = tokenize(term);
    const survivors = [];
    for (const t of raw) {
        if (QUERY_STOPWORDS.has(t)) continue;
        if (!survivors.includes(t)) survivors.push(t);  // duplicate-term dedup
    }
    const base = { ignoredCommon: [], files: [], filesByToken: new Map(), expectedBytes: null };
    if (raw.length === 0) return { ...base, mode: 'empty', tokens: [] };
    if (survivors.length === 0) return { ...base, mode: 'allStopwords', tokens: [] };

    const hot = manifest.hotTokens || {};
    const participating = [];
    const common = [];
    for (const t of survivors) {
        const h = hot[t];
        if (h && !h.fetchable) common.push(t);
        else participating.push(t);
    }

    if (participating.length === 0) {
        // Every surviving term is a common term: rank via the sidecar.
        return {
            mode: 'topk', tokens: common, ignoredCommon: [],
            files: ['hot_topk.parquet'],
            filesByToken: new Map(common.map(t => [t, ['hot_topk.parquet']])),
            expectedBytes: null,
        };
    }

    const filesByToken = new Map();
    const files = [];
    for (const t of participating) {
        const h = hot[t];
        const tokenFiles = (h && h.fetchable)
            ? Array.from({ length: h.sub_files },
                         (_, m) => `hot/${h.key}_p${m}.parquet`)
            : [shardFile(t, manifest.shardCount)];
        filesByToken.set(t, tokenFiles);
        for (const f of tokenFiles) if (!files.includes(f)) files.push(f);
    }
    let expectedBytes = null;
    if (shardSizes) {
        expectedBytes = 0;
        const counted = new Set();
        for (const t of participating) {
            const h = hot[t];
            if (h && h.fetchable) {
                if (!counted.has(h.key)) { expectedBytes += h.total_bytes; counted.add(h.key); }
            } else {
                const f = shardFile(t, manifest.shardCount);
                if (!counted.has(f)) { expectedBytes += shardSizes[f] ?? 0; counted.add(f); }
            }
        }
    }
    return {
        mode: 'normal', tokens: participating, ignoredCommon: common,
        files, filesByToken, expectedBytes,
    };
}

/**
 * BM25 contribution of one posting row (contract §5).
 * @param row     { field, tf, doc_len, df } — df is EMBEDDED in shipped rows
 *                (round-5 amendment; df.parquet is offline-only).
 * @param stats   { totalDocs, avgDocLenByField } — from build_stats.json:
 *                totalDocs = total_documents (distinct (pid, field) docs);
 *                avgDocLenByField[field] = fields[field].avg_doc_len
 *                (PER-FIELD corpus averages, matching the builder's
 *                hot_topk scoring).
 */
export function bm25Contribution(row, stats) {
    const idf = Math.log((stats.totalDocs - row.df + 0.5) / (row.df + 0.5) + 1);
    const avgDl = stats.avgDocLenByField[row.field];
    const norm = row.tf * (BM25_K1 + 1)
        / (row.tf + BM25_K1 * (1 - BM25_B + BM25_B * row.doc_len / avgDl));
    const weight = FIELD_WEIGHTS[row.field] ?? 1.0;
    return weight * idf * norm;
}

/**
 * Combine postings into the final AND-ranked top-K.
 *
 * @param postingsByToken  Map<token, Array<{pid, field, tf, doc_len, df}>>
 * @param stats            { totalDocs, avgDocLenByField }
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
