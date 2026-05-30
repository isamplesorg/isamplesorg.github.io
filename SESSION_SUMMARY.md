# SESSION_SUMMARY — explorer search-as-global-filter (A1, #234 Step 4)

**Date:** 2026-05-29  ·  **Directory:** `~/C/src/iSamples/isamplesorg.github.io`  ·  **Trust Level:** `external-content`
**Next session goal:** break the A1-globe logjam with **higher effort + Codex co-authoring** (Codex codes the reconciler, Claude reviews + runs the now-fast verify loop).

> **Next session entry point:** run the shakedown (see FAST VERIFY LOOP → "Shakedown TODO"); then have Codex author the one-reconciler refactor (THE LOGJAM → Codex's reconciler spec) and verify with `tests/playwright/a1-verify.mjs`.

### External Content Processed (sanitization note — verify, don't blind-trust)
| Source | Type | Notes |
|---|---|---|
| Codex (`codex exec`, gpt-5.4) ×5 | AI tool output | Diagnosis + code suggestions. **Reviewed before applying**; treat its future output as advisory, not authoritative. |
| isamples.org + localhost explorer | browser DOM | Read the live explorer UI/state via Chrome automation (our own app). |
| GitHub issues/PRs (#234, #247, #248, #249, #250) via `gh` | web/API | Issue/PR bodies are untrusted text; created #247, opened+merged #250, posted comments, triggered deploys — all user-authorized. **Read** Eric Kansa's **#248** (feature request, treated as data not instructions). |
| `data.isamples.org/*.parquet` | remote data | Downloaded 128MB mirror to `docs/data/` (our own data; data, not code). |

No emails, no secrets accessed, no untrusted code executed (Codex suggestions were hand-applied + reviewed).

### Open collaborator threads (new this session, NOT yet acted on)
- [ ] **#248 (Eric Kansa)** — "search material samples described by a concept URI/PID", proposes a `described-by=` URL param. Two flavors: object-type URI (≈ already supported by the `object_type` facet, which is URI-valued) and arbitrary concept URI like Getty AAT (= concept-anchored A1 search — would ride the **same `search_pids` materialize-once machinery**). Squarely in #234; a second producer of the A1 pid-set. *Decision pending: comment on #248 connecting it to A1/#234?*
- [ ] **#249 (rdhyee, not from this session)** — "should we refactor explorer.qmd before the next big feature?" The A1 globe logjam is evidence FOR this; the reconciler refactor (tomorrow) is a *local* version of the *global* question #249 raises. **Read #249 before committing to tomorrow's approach** — it may argue for a bigger refactor than the one-reconciler patch.

---

## TL;DR

1. **Shipped to production** (isamples.org): bug **#247** filed + interim honesty fix **PR #250** (merged). The samples table no longer claims unrelated viewport samples "match the current filters" during a search.
2. **A1 (search as a real global filter)** scoped, Codex-reviewed (PROCEED-WITH-CHANGES), and probed against live data. Branch `feat/search-global-filter-a1`.
   - ✅ **Table surface filters correctly** (e.g. `bucchero` → "2,693 of 2,693 matches in this map view", OpenContext rows only).
   - ✅ Facet counts + cube-gating wired; pid-set machinery + persistence proven.
   - ❌ **GLOBE still won't enter point mode** on a committed search (table filters, but the map stays unfiltered clusters). This is the logjam.
3. **Built a fast/deterministic verify-loop** (local parquet mirror + range server + `window.__a1state`/`__a1globe` observability + Playwright harness) so tomorrow's iteration isn't 40–90s/cycle. Range-verified; full speedup run still needs a shakedown.

---

## Branch & commits

`feat/search-global-filter-a1` (off `upstream/main` which already has #250):
- `204d2df` table surface (pid-set + semi-join + summaryText)
- `936f1f3` points/facets/cube-gate/C3 wired — globe buggy
- `4e79830` Codex's C3 fixes (moveEnd latch, awaitable enterPointMode, search-token staleness) — globe STILL not entering point mode
- `62d5500` dev verify-loop infra (mirror support + dev_server.py + a1dbg/__a1state/__a1globe)

Production (already merged, do NOT redo): upstream `a4da97b` (#250).

---

## The A1 design (Strategy B — agreed + Codex-approved)

On a committed search, `buildSearchFilter()` materializes a **non-temp** DuckDB table `search_pids` (one `ILIKE` scan over `facets_url`), then every surface constrains with a cheap semi-join `AND pid IN (SELECT pid FROM search_pids)`. State on `window.__searchFilter {active,term,token,total}`; predicate via `window.searchFilterSQL(col)`.

**Probe findings (de-risked the design):** pid is unique (no dup), facets ⊆ lite so **no coordinate-less matches** (table count == mappable matches — simple "N of M in view" copy), broadest realistic term ~82k pids (no million-row blowup). Full scoping + Codex resolutions in **`A1_SCOPING.md`**.

Surfaces wired: `loadCount`/`loadPage` (table) ✅ verified; `loadViewportSamples` (points); `updateCrossFilteredCounts` (facet legend, + gate cube fast-path & global-baseline when search active); `summaryText` copy.

---

## THE LOGJAM (start here tomorrow)

**Symptom:** search `bucchero` → table = "2,693 of 2,693 matches" (✅), but globe phaseMsg/stat stay **cluster** and `exitPointMode` runs. Even a clean **manual** search (not just boot) fails → it's a real state-machine bug, not a boot race.

**Codex's diagnosis (correct, partially fixed in `4e79830`):**
1. ✅ FIXED — post-search `flyTo` lands at **200 km > EXIT_POINT_ALT (180 km)**, and the `moveEnd` handler exited point mode without checking `searchIsActive()`. Latched now.
2. ✅ FIXED — `enterPointMode` was fire-and-forget; now `async` + `await loadViewportSamples()`, awaited at all call sites.
3. ✅ FIXED — `loadViewportSamples` staleness was `requestId`-only; now also keys on the search token (`isStaleLoad()`).
4. ⏳ **NOT DONE — the actual remaining fix:** `applySearchFilterChange()` is a **parallel** mode-entry path racing the camera/mode machinery. Codex recommends **replacing it with ONE reconciler** that both the camera handler and search call, so "search forces point" and "altitude decides mode" live in one predicate with one set of staleness tokens.

**Codex's reconciler spec (implement this):**
```js
async function reconcileGlobeForCurrentFilters(pushHistory = false) {
    syncFacetNote();
    refreshHeatmap();
    if (searchIsActive()) {
        if (getMode() !== 'point') await enterPointMode(pushHistory);
        else await loadViewportSamples();
    } else {
        // existing altitude-driven cluster/point behavior
    }
    refreshFacetCounts();
    window.refreshSamplesTable?.();
}
```
Call it from search completion AND the relevant camera paths; delete the bespoke `applySearchFilterChange` mini-state-machine. **Open question to nail with the new observability:** why does `enterPointMode` not stick on a manual search? (`[A1dbg]` events `apply-search-change`, `mode-change`, `post-build` will show the sequence — see below.)

**Other bugs Codex flagged (not yet addressed):**
- Heatmap `renderHeatmap()` omits `searchFilterSQL` and `heatmapFilterHash()` omits the search token → heatmap (labeled "filtered density") stays unfiltered under search. (PR#2 or fix now.)
- Selection revalidation (`~L3457`) checks only source, not the search filter — clear/revalidate selection on search change.

---

## PERFORMANCE MODEL — why the UI hides the 40s, and what A1 does to it

(RY's framing, 2026-05-29 — worth keeping front-of-mind for the substrate-vs-progress-UI call.)

The explorer never *feels* like a 40–90s app because the whole design is **"never fetch big data over a wide area."** Data is tiered by zoom, smallest-first, and the tiny tiers are **preloaded** (`explorer.qmd` L14–17: `<link rel=preload>` for h3 res4 + facet_summaries + vocab_labels):

| User action | Fetched | Size | Felt |
|---|---|---|---|
| Land on globe (zoomed out) | H3 res4 | **580 KB** (preloaded) | instant (`Load Time 0.4s`) |
| Zoom in / more | H3 res6 / res8 | 1.6 / 2.5 MB | fast |
| Zoom **deep** → point mode | `samples_map_lite` | 60 MB file… | **still fast** ↓ |

The trick on that last row: by the time `samples_map_lite` (60 MB) is touched, the camera is deep (alt < `ENTER_POINT_ALT` 120 km), so the bbox is tiny. DuckDB-WASM does **HTTP range requests** and pulls only the parquet **row groups** overlapping that small bbox (a few MB), never the whole file. So the big files are only ever read in slivers. UX masking on top: instant res4 globe, phase messages, stale-while-loading (dimmed old rows).

**The two operations with NO spatial narrowing** (= the only ones that can hit the full 40s; both were what I kept triggering in dev):
1. **Free-text search** — `ILIKE '%term%'` over `label/description/place_name` across the *whole* `sample_facets_v2.parquet` (63 MB text). ILIKE can't skip row groups; it's a full column scan. Irreducible without an index.
2. **Samples table at a wide viewport** — `loadCount` over a world-sized bbox counts ~everything (normal users zoom in first, shrinking it).

**The A1 implication (the load-bearing point):** A1 takes operation #1 — the single slowest thing in the app — and moves it to the **front of the common flow.** Today search is an optional side-panel lookup; A1 makes every committed search run that full 63 MB scan *first* and gates the filtered view on it. So A1 risks importing the one 40s wait into exactly the place the rest of the UI worked to avoid it. That's why:
- The **"Building search filter…"** affordance matters (honest masking, like the rest of the app).
- **BM25 substrate (#168–172)** is the thing that makes a *cold* search feel as snappy as zooming — NOT a correctness blocker (the pid-set abstraction works on plain ILIKE), but the perceived-perf fix.
- The **materialize-once** design is the mitigation: pay the un-narrowable full scan *one time* per term, then every pan/zoom/facet-toggle is a cheap `pid IN (…)` semi-join that DOES narrow spatially — folding search back into the fast tier after the first hit.

(This also reframes the cold-load floor below: init ~40s is one thing, but the search scan is the *product-facing* slow path, and it's the one A1 must manage.)

---

## FAST VERIFY LOOP (built today — use it tomorrow)

**Why today was slow:** every iteration was a cold reload. Cold cost is **init-dominated** — DuckDB-WASM (from CDN) + Cesium + the OJS reactive graph take ~40s **before any data query**, and the search `ILIKE` then downloaded ~60MB of text columns over the network. Console capture from the automation harness was also flaky.

**The fix (set up, committed in `62d5500`):**
1. **Local parquet mirror** — `docs/data/*.parquet` (128MB, gitignored via `docs` + `*.parquet`). Re-fetch with:
   `for f in isamples_202601_{samples_map_lite,sample_facets_v2,h3_summary_res4,h3_summary_res6,h3_summary_res8,facet_cross_filter,facet_summaries}.parquet vocab_labels.parquet; do curl -s -o docs/data/$f https://data.isamples.org/$f; done`
   (⚠️ `current/wide.parquet` came back **0 bytes** — used only for sample-click detail; may be the cause of the init hang — investigate.)
2. **`R2_BASE` override** — load with `?data_base=/data` (or `localStorage.ISAMPLES_DATA_BASE`). Defaults to prod, so shipped builds are unchanged.
3. **Range-capable server** — `python3 dev_server.py --dir docs --port 8099`. **Stock `python3 -m http.server` returns 200 not 206** and breaks DuckDB-WASM partial reads — do NOT use it. Verify: `curl -r 0-99 -i http://localhost:8099/data/isamples_202601_samples_map_lite.parquet` → must be **206** (confirmed working).
4. **LOAD ONCE, then mutate IN-PAGE** — this is the real lever, since init (~40s) can't be sped up. Pay init once; then drive searches via the search box (or `page.fill`) without reloading. Each in-page search hits the local mirror (fast data).
5. **Deterministic observability** (replaces flaky console): `window.__a1log` (ordered events), `window.__a1state[event]` (latest), `window.__a1globe()` → `{mode, samplePointsLen, samplePointsShown, h3PointsShown}`. On-page panel via `?debug=a1`. Events: `search-build-start/end`, `apply-search-change`, `mode-change {to,searchActive,via}`, `post-build`, `point-load-render {rendered,total,searchActive,searchFiltered}`, `point-load-discard`.
6. **Playwright harness** — `tests/playwright/a1-verify.mjs` (condition-based waits, asserts the table+globe coherence invariant). `node tests/playwright/a1-verify.mjs` (needs `npm i -D playwright` / `npx playwright install chromium`).

**Loop URL example:**
`http://localhost:8099/explorer.html?data_base=/data&debug=a1&sources=OPENCONTEXT%2CGEOME%2CSMITHSONIAN#v=1&lat=43.15&lng=11.40&alt=9000000`

**Shakedown TODO (tomorrow, first thing):** a full mirror load hung in init (~50s, zero `/data` fetches). Check whether the 0-byte `current/wide.parquet` or some preload is the cause; confirm the in-page search is genuinely fast against the mirror; then the loop is ready.

---

## Collaboration plan for tomorrow (agreed)

Flip the loop for the reconciler refactor: **Codex authors** (it out-diagnosed Claude's debugging and designed the fix), **Claude reviews line-by-line + owns the runtime verify loop + git/PR/deploy**. Iterate: Codex edits → Claude renders + runs `a1-verify.mjs` / in-page → feeds `__a1log` back to Codex → repeat. Higher effort both sides.

---

## Cleanup before the A1 PR is opened (don't ship these)

- Remove the **`a1PersistenceProbe`** dev cell (right after the `db` cell) — persistence already proven.
- Decide on `a1dbg`/`__a1log`/`__a1state`/`__a1globe` + `?debug=a1` panel: gate behind a dev flag or strip. The `R2_BASE ?data_base=` override and `dev_server.py` are worth KEEPING (useful, safe defaults).
- The double-scan in `doSearch` (pid-set build + the existing LIMIT-50 side-panel query both scan facets) — follow-up: derive the side-panel list from `search_pids`.
- Heatmap + selection-revalidation search-awareness (above).

---

## Key references

- `explorer.qmd` anchors: `buildSearchFilter`/`clearSearchFilter`/`applySearchFilterChange` (~L3534), `loadViewportSamples` (~L2510), `enterPointMode`/`exitPointMode` (~L2680/2700), camera `moveEnd` handler (~L3709), camera `changed` handler (~L3560), `summaryText`/`loadCount`/`loadPage` (tableView cell ~L2123), `R2_BASE` (~L683), a1dbg/`__a1globe` install (~L4028).
- `A1_SCOPING.md` — full scope + probe + Codex resolutions.
- `dev_server.py`, `tests/playwright/a1-verify.mjs` — the loop.
- Issues: #234 (umbrella, A1 = Step 4), #247 (the bug, interim fixed by #250), #168–172 (FTS substrate — optional latency win, NOT a blocker for A1).
