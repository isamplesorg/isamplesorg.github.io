# A1 Scoping — "search as a global filter" (#234 Step 4)

Goal: when a free-text search is committed, **every count/where surface reflects `searchTerm ∩ viewport ∩ source/facet filters`**, not just the side-panel results list. Currently search only drives a side list + camera fly; the table, point loader, facet counts, stats, and globe ignore it (axis A2). #250 (interim) only relabels the table; this is the real fix.

## 1. Data-model reality (the constraint that shapes the design)

The search predicate (`textSearchWhere`) matches **3 columns**: `label`, `description`, `CAST(place_name AS VARCHAR)` — all read from **`facets_url`** (`sample_facets_v2.parquet`). `description` was deliberately moved to facets_url in #168 *because* the search needed it.

| Surface | Function | Reads from | Has search cols? |
|---|---|---|---|
| Samples table (count + page) | `loadCount` / `loadPage` | `lite_url` (samples_map_lite) | **label + place_name only — NO `description`** |
| Point-mode dots | `loadViewportSamples` | `lite_url` | NO description |
| Facet legend counts | `updateCrossFilteredCounts` | `facets_url` (global) **or** `facets_url ⋈ lite_url` (bbox path) | **YES — facets_url has all 3** |
| Facet counts cube fast-path | (cross_filter parquet) | `cross_filter_url` (pre-aggregated) | **NO — globally pre-aggregated, cannot be text-filtered** |
| Globe clusters | H3 summary parquets | `*_h3_summary_res{4,6,8}` | **NO — pre-aggregated, `dominant_source` only** |
| Heatmap | wide/lite | — | NO description |
| "Samples in View" stat | derived from above | — | follows its surface |

Two hard truths:
1. **`description` is only in facets_url.** Any surface that queries `lite_url` (table, points) must reach facets_url to get full search parity — i.e. a JOIN — or accept reduced recall (label+place_name only).
2. **Pre-aggregated surfaces can never be text-filtered** (cube fast-path, H3 clusters). They must be *gated off* (cube) or handled by a mode switch / honest warning (clusters) when a search is active.

## 2. Two implementation strategies

### Strategy A — per-surface ILIKE (the naive wiring)
AND `searchWhere` into every query; JOIN facets_url where description is needed (table, points). Reuse the existing B1 `facets ⋈ lite` JOIN shape.
- ✅ Minimal new concepts; reuses existing patterns.
- ❌ **Perf**: `ILIKE '%term%'` is a full scan (no index). On staging, *one* search query was **42s cold / 17s count** over facets_url (6.7M rows). A1-naive runs an ILIKE scan on **every** count surface (table count, table page, 4× facet dims, point loader, heatmap) on **every** camera move / filter toggle → ~7 cold ILIKE scans per interaction. Almost certainly unacceptable. This is exactly the worry in #234 OQ4 ("may want the BM25 substrate #168-172 first").

### Strategy B — materialized search pid-set (RECOMMENDED)
Run the ILIKE **once per search term** to materialize the **set of matching pids** (e.g. bucchero → 2,693 pids), then constrain every other surface with a cheap **`pid` semi-join / `pid IN (…)`** against that held set. The ILIKE cost is paid once per *term change*, not per *interaction*; pan/zoom/facet-toggle just re-filter the held pid-set by bbox/facets (indexed-ish, cheap).
- ✅ Decouples A1 perf from interaction frequency — the expensive scan happens once.
- ✅ Works **without** the #168-172 BM25 substrate for moderate result sets.
- ✅ Single source of truth: same pid-set feeds table, points, facet counts, stats — guaranteed coherence.
- ⚠️ Materialize via a **registered DuckDB temp table** (`search_pids`) and semi-join, NOT a giant literal `IN (…)` — broad terms (`pottery` ≈ 7k+, or worse) make the literal unwieldy; a temp table scales and keeps SQL clean.
- ⚠️ Recompute the pid-set when the term changes; invalidate/drop on clear. The set is "all matching pids" (no LIMIT 50 — that cap is only for the side list).
- ⚠️ Very broad terms (e.g. single common word) could match millions of pids → temp table large but still a bounded one-time cost; semi-join stays cheap. Worst case is comparable to today's no-search counts.

**Recommendation: Strategy B.** It's the design that makes A1 shippable on the current parquets and naturally coherent. The BM25 substrate (#168-172) then becomes a *latency optimization* for the one-time pid-set computation, not a prerequisite.

## 3. Per-surface changes (Strategy B)

1. **Materialize pid-set** (new): on committed search, `CREATE OR REPLACE TEMP TABLE search_pids AS SELECT pid FROM read_parquet(facets_url) WHERE <searchWhere>`. Expose readiness via the existing cross-cell channel (extend `window.__explorerActiveSearch` → also a `searchPidsReady` flag / token). Drop/disable when search cleared.
2. **Table** `loadCount` / `loadPage` (`lite_url`): add `AND pid IN (SELECT pid FROM search_pids)` (semi-join) when search active. No description JOIN needed — the pid-set already encodes the description match.
3. **Point loader** `loadViewportSamples` (`lite_url`): same semi-join predicate.
4. **Facet counts** `updateCrossFilteredCounts`: add the semi-join to BOTH the global and bbox paths; **gate off the cube fast-path** when search active (like bbox already gates it). facets_url path already has the columns; semi-join keeps it uniform.
5. **"Samples in View" stat**: follows the surface it's derived from — recheck both cluster-mode and point-mode stat computations use the filtered count.
6. **Globe**: clusters (H3) can't be filtered. Adopt #234's **C3-when-feasible**: when a search is active, prefer point mode (points ARE filterable via semi-join); if over the density cap, keep clusters + **prominent "showing clusters — not filtered by your search" warning** (reuse the `#facetNote` honesty pattern). *Proposed: defer full C3 to a follow-up; in the first A1 PR, show the honest warning + keep #250's panel pointer.*
7. **Heatmap**: filter-honest density should also semi-join. *Proposed: include if cheap, else defer with a tracked note.*

## 4. Cross-cell state & staleness

- Already have `window.__explorerActiveSearch` (term) from #250. Add the temp-table lifecycle + a `searchToken` so surfaces can detect a superseded search.
- Reuse existing cancellation primitives: `pageGen` (table), `requestId` (points), `facetCountsReqId` (facets). Each must re-read the current search state on every async resume (same stale-guard pattern already in place).
- Order: materialize pid-set BEFORE kicking the dependent refreshes; `window.refreshSamplesTable?.()` + `refreshFacetCounts()` already exist as hooks.

## 5. Progressive refinement (perf UX, optional in v1)

Per #234, surfaces can show a coarse/stale value during active panning (`.recomputing` italic) then settle. With Strategy B the per-pan cost is already just a semi-join, so progressive refinement is likely **not needed for v1** — revisit only if semi-join + bbox on lite is still janky cold.

## 6. Edge cases to honor

- Search cleared / <2 chars → drop temp table, revert all surfaces to non-search (the #250 flag-clear path already exists; extend it).
- Term changed mid-flight → token invalidates the old pid-set; rebuild.
- Coordinate-less matches → counted by facet counts (facets_url) but absent from map/table (lite has no row). Decide: does the table count match the side-panel total? Likely NOT (table requires coords). **Must reconcile the messaging** so "N in view" vs "2,693 results" don't reintroduce confusion.
- Area-scope vs world-scope search: A1 makes scope less meaningful (the whole page is filtered); confirm the scope toggle still behaves.
- `escSql` / injection: the pid-set query reuses the existing escaped `searchWhere`; the semi-join carries no user input.

## 7. Proposed scope split

- **A1 PR #1 (core):** materialize pid-set; wire table (count+page), point loader, facet counts (+ gate cube), stats; honest cluster warning. This delivers "table/points/legend reflect bucchero ∩ viewport".
- **A1 PR #2 (follow-up):** C3 auto-point-mode promotion; heatmap semi-join; progressive refinement if needed.
- **Substrate (#168-172):** optional latency win for the one-time pid-set scan; not a blocker for PR #1.

## 8. Open questions for review

1. **Strategy B temp-table semi-join** — is a `CREATE TEMP TABLE search_pids` + `pid IN (SELECT …)` the right DuckDB-WASM pattern, vs a registered Arrow table or a literal IN-list? Any WASM-specific gotcha (temp table lifetime across queries in the same connection)?
2. **Coordinate-less matches** — how to keep "samples in view" vs "2,693 results" from re-confusing users once the table IS search-filtered? (The table can only ever show coord-bearing matches.)
3. **Cluster honesty in v1** — is "warn + keep #250 panel pointer" enough for the first A1 PR, or must C3 (auto-point) land together so the globe isn't visibly unfiltered while everything else is?
4. **Is the one-time ILIKE scan acceptable** at ~17-42s cold for the first search, or does even the *one-time* cost demand #168-172 first? (Caching/warm makes subsequent fast; cold-first-search is the concern.)
5. **Broad-term blow-up** — any term matching millions of pids: temp table size / semi-join cost acceptable, or cap + warn?

---

# Codex review resolutions (incorporated) — verdict: PROCEED-WITH-CHANGES

Strategy B confirmed as the right direction. Required changes folded into the plan:

### Strategy B hardening
- Materialize as `CREATE OR REPLACE TEMP TABLE search_pids_next AS SELECT DISTINCT pid FROM read_parquet(facets_url) WHERE pid IS NOT NULL AND <searchWhere>` — **DISTINCT + NOT NULL** (facets_url is facet-shaped → duplicate pids are real and would corrupt any join form).
- **Token-versioned / atomic swap**: build `search_pids_next`, then swap to `search_pids` only if the build's token is still current. A fixed name + async UI refreshes is race-prone.
- **Text-only pids** — do NOT bake source/facet/viewport into `search_pids`. Materialize on the term alone; apply source/facet/bbox downstream. This keeps a term change (rebuild) separate from a filter toggle (cheap re-filter).
- **Keep it inside DuckDB** — a registered Arrow table is worse here (extra JS↔WASM copies + browser memory); the pid set is produced by SQL, so leave it there unless measurement says otherwise.
- **Dev/startup assertion** (do FIRST, before building on it): create a temp table, query it from a *second* `db.query()`, drop it — proves the Observable `DuckDBClient.of()` wrapper reuses one session so the temp table survives across `db.query()` calls. Don't discover this through A1 behavior.
- **Measure before committing**: `EXPLAIN` / time `pid IN (SELECT …)` vs explicit `SEMI JOIN` / `EXISTS`. "Cheap" only holds vs repeated text scans — for million-row matches it's "scan + hash-probe," ~unfiltered-count + overhead, not free.

### Coordinate-less matches → first-class UX (not a footnote)
The table can only ever show coord-bearing matches, so it will NOT equal the global text-match count. Use **two named counts** instead of one:
- `2,693 text matches` (the search-results line)
- `N mappable samples in this map view matching "bucchero"` (the table meta), with `…of 2,693 total text matches (some have no coordinates)` when they differ.
This **replaces** #250's interim `summaryText()` disclaimer.

### Globe coherence — C3 moves INTO PR #1 (the coherence line)
Do NOT ship A1 with the dominant map layer (clusters) visibly unfiltered while table/legend are filtered — that's an internally contradictory half-state, arguably worse than today. PR #1 MUST: when search is active, **auto-promote to point mode if filtered-in-view count < point budget** (points are filterable via the semi-join); only **over the density cap** fall back to clusters + the prominent "showing clusters — not filtered by your search" warning.

### Revised scope split
- **PR #1 (A1 core):** dev assertion → pid-set materialization (versioned) → table (count+page) + point loader + facet counts (+ gate cube) + stats + **C3 auto-point-mode** + two-named-counts UX.
- **PR #2:** heatmap semi-join (or clearly disable/label heatmap while search active in PR #1), progressive refinement (likely unneeded with Strategy B), substrate-backed pid-set builder.

### Substrate (#168-172)
Not *logically* required — the pid-set is the abstraction boundary BM25 can later sit behind. BUT a 17–42s cold first search may be a product blocker. **Gate PR #1 on measured cold browser perf** for 3–5 representative terms incl. a broad/common term and a no-match term. If typical cold is still tens of seconds → ship only with explicit "Building search filter…" progress UI + cancellation, OR do the substrate first.

### Also add
- Search token in **every** stale guard (alongside `pageGen` / `requestId` / `facetCountsReqId`).
- **Broad-term policy**: warn / require refinement / "too many matches to render globally" fallback.
- **Update `EXPLORER_STATE.md`** — A1 changes the page's state contract, not just implementation.

---

# A1 gating probe — measured against live parquets (DuckDB v1.4.0, 202601 data)

| Finding | Result | Impact on plan |
|---|---|---|
| **Dup-pid risk** | facets = 5,980,282 rows = 5,980,282 **distinct** pids (pid is unique). lite = same 5,980,282. | `DISTINCT` is harmless hygiene but pid is already unique — no corruption risk. |
| **Coordinate-less matches** | bucchero 2,693 text → **2,693** coord-bearing; pottery 82,312 → **82,312**; soil 2,969 → **2,969**. facets pid-set ⊆ lite pid-set (identical counts). | **Codex concern #2 largely dissolves**: in the current data *every* searchable sample has coordinates. Table count = (text ∩ viewport); globally text-matches == mappable. UX simplifies to **"N of 2,693 matches in this view"** — no scary "some have no coordinates" caveat needed (keep a defensive branch, but it's not the common case). |
| **Broad-term magnitude** | pottery (broadest realistic) = **82k** pids, not millions. soil = 3k. | Temp-table + semi-join over ~10^4–10^5 pids is trivial. Broad-term-blowup is a non-issue for real terms; still cap a pathological single-letter term. |
| **ILIKE scan cost (native, lower bound)** | full text scan ~0.4–1.8s native warm. | WASM cold is the real cost (observed ~17–42s cold over HTTP range). **The one-time materialization latency remains the only real gating risk** → "Building search filter…" progress UI + cancellation, or substrate (#168-172) as latency win. |

**Net:** Strategy B is confirmed and *simpler* than feared. The coordinate-less reconciliation (Codex #2) is mostly moot on current data; the broad-term blowup (Codex #5) doesn't occur for real terms. The single remaining gate is **cold WASM materialization latency** — to be measured in-browser next (native timing is only a lower bound), deciding progress-UI vs substrate-first.
