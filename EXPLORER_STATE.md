# Explorer State Contract

Doc-only contract for `explorer.qmd`. Locks down where every piece of explorer
state lives, who owns it, when it gets written, and what the cross-filter rules
are. Resolves [#164](https://github.com/isamplesorg/isamplesorg.github.io/issues/164);
unblocks the items in [#163](https://github.com/isamplesorg/isamplesorg.github.io/issues/163).

**Direction**: imperative + URL-as-canonical-state. OJS cells are used as a
DAG-aware bootstrap (run viewer once, run phase1 after viewer is ready, etc.),
not as a reactive UI runtime. All user-driven UI updates go through
`writeQueryState()` → `history.replaceState` and direct DOM mutation. Reading
DOM checkboxes is the source of truth for facet state inside SQL builders;
the URL is the source of truth across reloads.

All file:line references below are against `explorer.qmd` at commit
`94e7674` (the tree this doc is being written against).

---

## 1. URL query params (`location.search`)

| field | owner | default | URL repr | hydration site | write-back trigger | validation | notes |
|-------|-------|---------|----------|----------------|--------------------|------------|-------|
| `search` | DOM `#sampleSearch` value | omitted | raw string | `applyQueryToSearch()` at start of `phase1` (`:937`) | `writeQueryState()` (`:445-446`) called from `doSearch()` (`:1789`) and from globe/table toggle | trim only; min 2 chars enforced at search time, not in URL | written even on no-result searches |
| `sources` | DOM `#sourceFilter` checkboxes | omitted (= all 4 checked) | CSV of `SOURCE_VALUES` ∩ user-checked | `applyQueryToSourceFilter()` at start of `phase1` (`:938`) | `writeQueryState()` from source filter `change` (`:1620`) | filtered by `SOURCE_VALUES` allowlist (`:407`); param removed when all 4 checked (`:449`) | empty (zero checked) renders as `&sources=` and yields `1=0` predicate (`:379`) |
| `material` | DOM `#materialFilterBody` checkboxes | omitted (= no filter) | CSV of full URIs | `applyQueryToFacetFilters()` at end of `facetFilters` (`:1061`) | `writeQueryState()` from `handleFacetFilterChange` (`:1642`) | none — checkbox `value` already constrained by render | empty checked set ⇒ param removed (`:459`) |
| `context` | DOM `#contextFilterBody` checkboxes | omitted | CSV of full URIs | same as `material` | same as `material` | none | same |
| `object_type` | DOM `#objectTypeFilterBody` checkboxes | omitted | CSV of full URIs | same as `material` | same as `material` | none | same |
| `view` | `body.classList.contains('table-view-active')` | omitted (= globe) | `table` only; absent ⇒ globe | `tableView` cell reads `params.get('view')` (`:1239-1240`) and calls `setView(...)` with `updateUrl=false` | `writeQueryState()` from `setView(mode, true)` via globe/table button clicks (`:1217-1218`, `:1210`) | only `table` is honored (`:1240`) | `writeQueryState()` reads body class, not `viewer.*` |
| `page` | inner closure `let page = 0` in `tableView` (`:1080`) | not in URL | — | — | resets to 0 on `refreshTable()` (`:1163`); ±1 on prev/next (`:1219-1220`) | clamped to `[0, totalPages-1]` (`:1112`) | **#163 item 6** — table page is intentionally not URL state today; if/when added, must coexist with the cross-filter contract below |
| `perf` | — (read-only feature flag) | omitted | `1` to enable | `perfPanel` cell reads (`:1921-1922`) | never written | `=== '1'` exact match | never round-tripped; safe to add other tail params |

### Quarto site-search collision

`?q=` is hijacked by Quarto's site-wide search and stripped via `replaceState`
(see comment at `:414-416`). That is why the explorer uses `?search=` for the
sample text query. Don't migrate to `q`.

---

## 2. URL hash params (`location.hash`)

The hash is the camera/deep-link channel. Always written together by
`buildHash(viewer)` (`:597-613`), always read together by `readHash()`
(`:583-595`).

| field | owner | default | hash repr | hydration site | write-back trigger | validation | notes |
|-------|-------|---------|-----------|----------------|--------------------|------------|-------|
| `v` | constant | `'1'` (always written) | `v=1` | `readHash()` returns `parseInt() || 0` (`:586`) | `buildHash` always sets `'1'` (`:601`) | `parseInt`; non-numeric ⇒ 0 | reserved for future schema bump |
| `lat` | `viewer.camera.positionCartographic` | absent | 4-decimal degrees | `readHash()` (`:587`); applied in viewer `once` postRender (`:797-812`) | camera-change debounced 600ms (`:1700-1702`, `replaceState`); enter/exit point mode (`:1463`, `:1474`, `pushState`); sample/cluster click (`:861`, `:888`, `pushState`); share button (`:1763`, `replaceState`) | clamped `[-90, 90]` (`:587`) | written together with `lng`, `alt` |
| `lng` | same | absent | 4-decimal degrees | same | same | clamped `[-180, 180]` (`:588`) | |
| `alt` | same | `null` ⇒ falls back to `20000000` (`:801`) | integer meters | same | same | clamped `[100, 40_000_000]` (`:589`) | |
| `heading` | `viewer.camera.heading` | `0` | degrees, 1-decimal | same | same; only written if `\|heading\| > 1` (`:607`) | clamped `[0, 360]` (`:590`) | |
| `pitch` | `viewer.camera.pitch` | `-90` | degrees, 1-decimal | same | same; only written if `\|pitch + 90\| > 1` (`:608`) | clamped `[-90, 0]` (`:591`) | |
| `mode` | `viewer._globeState.mode` | omitted (= `cluster`) | `point` only | `readHash()` (`:592`); applied after camera flight in `hashchange` handler (`:1727-1729`); also restored from `_initialHash` after zoomWatcher init | `buildHash` only writes if `'point'` (`:610`); push triggers as above | exact-match `'point'` | absence ⇒ cluster |
| `pid` | `viewer._globeState.selectedPid` | omitted | sample pid string (URL-encoded) | `readHash()` (`:593`); applied at end of `zoomWatcher` (`:1873-1901`) and on `hashchange` (`:1733-1756`) | sample-click sets it (`:860`); cluster-click clears it (`:887`); written in `buildHash` if non-null (`:611`) | none beyond `null` check | drives a `lite_url` lookup + lazy `wide_url` description fetch |
| `h3` | `viewer._globeState.selectedH3` | omitted | canonical 15-char lowercase hex (e.g. `843f6d3ffffffff`) | `readHash()` parses; boot deep-link calls `fetchClusterByH3` then `hydrateClusterUI` under a `_selGen` race guard; same path on `hashchange` | cluster-click sets `selectedH3 = meta.h3_cell` and clears `selectedPid` (mutual exclusion); sample-click clears `selectedH3`; source-filter change re-validates and may clear or rehydrate; written in `buildHash` if non-null | strict `/^[0-9a-f]{15}$/i`; cell-mode (`lower[0] === '8'`); resolution nibble in `RES_TO_H3_URL` map (4/6/8) | drives a single `WHERE h3_cell = CAST('<decimal>' AS UBIGINT) AND <sourceFilterSQL>` lookup against the resolution-routed parquet. h3_cell column is UBIGINT so SELECTs cast to VARCHAR and JS converts via `BigInt(dec).toString(16)` to avoid Number precision loss. `&pid=` wins if both present. Per `EXPLORER_CLUSTER_URL_PROPOSAL.md` |

### Hash write-vs-read coordination

`viewer._suppressHashWrite` (boot at `true` at `:791`, cleared at `:1904`)
prevents the camera-change handler from rewriting the hash while the
`hashchange` handler is mid-flight. The `_suppressTimer` (`:792`, `:1725`)
re-arms after a 2-second flight settles. **Do not remove this flag** without
re-deriving the camera→hash→camera echo prevention.

### `back/forward` listener

`window.addEventListener('hashchange', ...)` at `:1708` does the inverse of
`buildHash`: flies the camera, restores the selected pid, and toggles
`enterPointMode(false)` / `exitPointMode(false)` (the `false` suppresses a
nested `pushState`).

---

## 3. DOM-as-state

State that lives only on the page tree. Authoritative because some of it
predates the store-on-`viewer` pattern and isn't worth migrating.

| location | role | written by | read by | notes |
|----------|------|------------|---------|-------|
| `document.body.classList['table-view-active']` | view marker (table vs globe) | `setView()` in `tableView` (`:1198`) | `writeQueryState()` (`:462`); `isTableViewActive()` (`:755`) | URL `view` param is **derived** from this class, not the other way around |
| `data-facet`, `data-value` on `.facet-row` and `.facet-count` | facet selectors for in-place count mutation | rendered in `renderFilter` (`:1053`) and the static source legend (`:270-273`) | `applyFacetCounts()` (`:553-565`) | rebuilding the HTML would lose mid-interaction selections; `data-*` attrs are why we mutate counts in place |
| `data-lat`, `data-lng`, `data-pid` on `.sample-row` | click-to-fly payload for search/nearby results | rendered in `doSearch()` (`:1822`) and `updateSamples()` not currently using data-* (only the search list does) | search-row click handler (`:1832-1845`) | the nearby-samples list does not have data-* today; click-to-fly only works from the search list |
| `.recomputing` on `.facet-count` | transient "loading" styling during cross-filter recompute | `markFacetCountsRecomputing()` (`:570`) | `applyFacetCounts()` clears it (`:562`) | UI-only; not state in the persistence sense |
| `.zero` on `.facet-row` | "value has zero count under current filters" styling | `applyFacetCounts()` (`:565`) | CSS only | derived; do not read |
| `.disabled` on `#sourceFilter .legend-item` | unchecked source visual | `updateSourceLegendState()` (`:395-400`) | CSS only | derived from checkbox `checked`; do not read |

DOM input elements (the four facet checkbox bodies + `#sampleSearch` + `#maxSamples`)
are the **source of truth** for `getActiveSources()`, `getCheckedValues()`,
`getTableMaxSamples()`, and the search input. SQL builders read these
directly each call.

---

## 4. Widget-internal state (`viewer.*` / `window.*`)

Set on the Cesium `Viewer` instance during the `viewer` cell so it survives
across cells without becoming a separate OJS reactive value.

| field | type | set at | read at | role |
|-------|------|--------|---------|------|
| `viewer._globeState` | `{ mode: 'cluster'|'point', selectedPid: string|null }` | init `:789`; mutated `:860, :887, :1460, :1470, :1734, :1754, :1875` | `buildHash` (`:609-611`) | authoritative client-side mode + selection; the URL hash is its serialization |
| `viewer._initialHash` | `readHash()` snapshot | init `:790` | viewer first-frame `once` (`:797`); zoomWatcher boot deep-link (`:1873`) | preserves boot-time hash for late hydration |
| `viewer._suppressHashWrite` | bool | init `true` `:791`; cleared `:1904`; re-set/cleared in `hashchange` (`:1712`, `:1725`) | camera-change handler (`:1700`) | echo-loop guard |
| `viewer._suppressTimer` | timer handle | `:792`, `:1713`, `:1725` | cleared in `:1713` | re-arms `_suppressHashWrite` after camera flight |
| `viewer._clusterData` | `Array<row>` | `:964` (phase1), `:1305` (loadRes) | `countInViewport` (`:1342`); zoom recompute (`:1690`) | viewport count cache |
| `viewer._clusterTotal` | `{ clusters, samples }` | `:965`, `:1306` | exitPointMode (`:1481`); zoom recompute (`:1693`) | totals for the "in view / loaded" stat |
| `viewer._baselineCounts` | `{ source: Map, material: Map, context: Map, object_type: Map }` | `:1030-1035` | `applyFacetCounts()` (`:552`) | unfiltered facet counts; rendered when no cross-filter is active |
| `viewer.h3Points` | Cesium `PointPrimitiveCollection` | `:815` | cluster mode rendering | |
| `viewer.samplePoints` | Cesium `PointPrimitiveCollection` | `:818` | point mode rendering | |
| `viewer.pointLabel` | Cesium label entity | `:823` | mouse-move handler (`:836-848`) | hover tooltip |
| `viewer._selGen` | int | bumped by every `freshSelectionToken()` call (in zoomWatcher cell) | snapshot captured by each handler that mutates selection | freshness counter; see invariant below |
| `window.refreshSamplesTable` | `() => Promise<void>` | `:1238` | external (debug / Playwright) | not used by other cells; safe to keep or remove |

### Async-selection invariant

Any async work that updates `viewer._globeState`, the URL hash, or the side-panel DOM **must check freshness after every await**. The `freshSelectionToken(viewer)` helper (defined at top level alongside `readHash` / `buildHash` so both the viewer-cell click handler and the zoomWatcher-cell handlers can reach it) is the primitive: each user-input event handler that touches selection (cluster/sample click, hashchange, source-filter toggle, boot deep-link) calls it once at start to bump `_selGen` and capture an `isStale()` closure; every subsequent await is followed by `if (isStale()) return;` before any state/URL/DOM mutation. Pass `isStale` into nested helpers (`hydrateClusterUI`'s second param) so their internal awaits also bail before touching the DOM.

This invariant exists because there's no central "selection store" — selection state lives in `_globeState`, the URL hash, and the side-panel DOM, and four different paths (click, hashchange, filter, boot) write to all three. Without the freshness check, a slow earlier handler can repaint the side panel for a selection the user has already moved off of. Issue #187 has the post-mortem on the 6-round Codex review that motivated extracting the primitive.

### `_urlParamsHydrated` — confirmed gone

Grep for `_urlParamsHydrated` in `explorer.qmd` returns no hits. The flag from
PR #159's first cut was removed; the new contract is "URL → DOM hydration runs
exactly once per cell that owns the corresponding DOM, gated only by the OJS
DAG (phase1 ⇒ source/search hydration; facetFilters ⇒ facet hydration;
tableView ⇒ view hydration)."

---

## 5. OJS cell graph

Document order, with declared dependencies and side effects. The cells form
a fan-out from `viewer` + `db`:

```
Cesium-token    [pure global mutation]
constants/helpers  [pure; defines URLs, palettes, ~40 helper functions]
db                 [DuckDBClient.of()]
viewer             [creates Cesium viewer; reads readHash() once]
  └── phase1       [needs viewer + db; runs URL→DOM hydration for search + sources]
        └── facetFilters    [needs phase1; loads vocab + summaries; sets _baselineCounts; runs URL→DOM hydration for facet checkboxes]
              ├── tableView    [needs facetFilters; reads view from URL once]
              └── zoomWatcher  [needs facetFilters; registers ALL change handlers; runs deep-link pid restore]
                    └── perfPanel  [opt-in; needs phase1; renders perf panel if ?perf=1]
```

| cell | line | implicit deps | DOM mutation | event listeners registered | URL writes |
|------|------|----------------|--------------|----------------------------|------------|
| Cesium token | `:328` | — | — | — | — |
| constants/helpers | `:333` | — | — | — | — |
| `db` | `:759` | — | — | — | — |
| `viewer` | `:773` | — | `#cesiumContainer` mounts globe | `scene.postRender`×2; mouse-move; left-click | `pushState` (sample/cluster click) |
| `phase1` | `:930` | `viewer`, `db` | `#sourceFilter` (via hydration); stats DOM | — | — |
| `facetFilters` | `:979` | `phase1`, `db` | `#materialFilterBody`, `#contextFilterBody`, `#objectTypeFilterBody`; facet count text | — | — |
| `tableView` | `:1071` | `facetFilters` | `#globe-layout`, `#tableContainer`, `#tableControls`, `#samplesTable`, `body.classList` | globe/table buttons; prev/next; max input; **change** on all four facet bodies | `replaceState` via `writeQueryState` (`view` flip) |
| `zoomWatcher` | `:1246` | `phase1`, `facetFilters`, `db` | facet count text; stats; phase msg; sample card; samples list | source filter `change`; material/context/object_type `change`; `camera.changed`; `window` `hashchange`; share button; search button; search input keydown | `pushState` and `replaceState` via `buildHash` (camera, mode flip, sample fly); `replaceState` via `writeQueryState` (filter changes, search submit, share) |
| `perfPanel` | `:1910` | `phase1` | `#perfPanel` floating div | close button | — |

Note that **two cells register `change` listeners on the four facet container
elements**: `tableView` (`:1233-1236`) marks the table dirty and refreshes if
visible, and `zoomWatcher` (`:1617`, `:1649-1651`) reloads the globe and
debounces the cross-filter count refresh. Both listeners fire on every facet
change; this is intentional (each cell handles its own concerns) but is the
single most "magical" coupling in the file — touch with care.

---

## 6. Search-semantics decision

The issue originally presented two options (A) global filter and (B) side-panel
lookup. After Codex review on #165, we committed to a sharper third framing:
**(C) side-panel lookup with result-pin overlay**, which is a refinement of
(B) — the *backend* is unchanged (search does not alter cluster/sample/facet
data sources), but the *UI surface* gains a temporary point-overlay
visualization of the matching samples.

### What "search" does today (`doSearch` at `:1782-1859`)

Reads `#sampleSearch.value`. Runs an ILIKE-based DuckDB query against
`lite_url` over `label` and `place_name`, with `sourceFilterSQL()` and
`facetFilterSQL()` AND'd in. Renders up to 50 ranked results into
`#searchResults` (count) and `#samplesSection` (list). Click a result row to
fly the camera. **The map clusters/samples are not filtered by the search
text. Facet counts are not filtered by the search text.** The URL `search`
param is written via `writeQueryState()` (`:1786`, `:1789`).

That is option (B) verbatim, and it matches the facet-count fix Codex landed
in [#158](https://github.com/isamplesorg/isamplesorg.github.io/pull/158).

### The three options

- **(A) Global filter.** Active search restricts the map layer, table, and
  facet counts to the matching subset. Forces cluster mode to drop to point
  mode whenever a search is active (H3 summaries are not text-indexable).
  Couples search semantics to camera/mode state. **Rejected.**
- **(B) Side-panel lookup.** Search populates the side panel only; map +
  facet counts ignore it. Today's behavior. Leaves [#163 item 4](https://github.com/isamplesorg/isamplesorg.github.io/issues/163)
  as a UX wart (zero results + populated map). **Insufficient.**
- **(C) Side-panel lookup with result-pin overlay.** Search populates the
  side panel **and** renders a temporary point-overlay of the matching
  samples on the globe — independent of the H3 cluster layer and the facet
  counts. The cluster layer remains accurate (no facet-aware text indexing
  required); the overlay visualizes "your search matched these samples,
  here are their locations." Cleared when the user clears the search. **Adopted.**

### Decision: (C) side-panel lookup with result-pin overlay

**What stays the same as (B).** The backend / data-source contract is
unchanged from option (B):

1. The H3 summary parquets carry only `dominant_source`, `sample_count`,
   and centroid coords. Cluster mode is **not** text-aware.
2. The cross-filter facet-count contract landed in #158 still excludes
   search from the count predicate.
3. `viewer._globeState` does not gain a search-active mode; the cluster
   primitive collection is unaffected.

**What's new in (C).** A *third* primitive collection on the viewer:
`viewer.searchResultPoints` (Cesium `PointPrimitiveCollection`), styled
distinctly from cluster and sample-mode points (e.g., outlined ring rather
than filled dot, distinct color). Owned by `zoomWatcher`'s search handler,
not the cluster/sample-mode handlers. Lifecycle:

- Populated by `doSearch()` after results are computed. One pin per result,
  positioned at `(longitude, latitude, 0)`. Opt-in to picking (clicking a
  pin behaves like clicking a sample-mode point: `updateSampleCard()` +
  `pid` hash write).
- Cleared by:
  - User clears the search input (or `?search=` is removed from URL).
  - User triggers a new search (overlay is replaced with new results).
- Shown in both globe cluster mode and point mode. The cluster layer
  remains accurate; the overlay is layered above as visual answer to
  "where did my search land geographically."

**Why (C) over (B).**

- Solves [#163 item 4](https://github.com/isamplesorg/isamplesorg.github.io/issues/163)
  cleanly: zero results render zero pins (and the populated map clusters
  remain visibly *not* the search results, distinguishable by styling).
  Non-zero results show a coherent visual answer.
- Preserves the "imperative globe; URL-canonical state" framing — cluster
  and facet behavior is unaffected, no reactive cascade.
- Doesn't conflate "search matched these samples" with "active filter"
  (which is what option A does); the user retains source/facet/view as
  independent orienting controls.

**Costs of (C) we accept.**

- One additional Cesium primitive collection. The viewer cell at `:773`
  needs a `v.searchResultPoints = new Cesium.PointPrimitiveCollection()`
  alongside the existing `h3Points` and `samplePoints`.
- One additional `data-pid` data path: the search-result pin click handler
  duplicates the sample-mode click handler. Acceptable; both paths are
  small.

### Implementation rules for option (C)

These are not negotiable defaults during implementation:

| concern | rule |
|---------|------|
| **Pin count cap** | maximum **50** pins, matching the existing search result `LIMIT 50` (the *displayed* result set size). The full match set may exceed 50; the substrate query truncates to top-K before pin rendering. Pin count therefore equals `min(50, total_matches)`, never more, never fewer |
| **Z-order** | search-result pins render **above** both H3 cluster points and sample-mode points. Implementation: add `searchResultPoints` to `scene.primitives` *after* `h3Points` and `samplePoints` |
| **Pin styling** | hollow ring with bright outline (distinct from cluster filled-dot and sample-mode small filled-dot). Color follows the source palette (`SOURCE_COLORS`) so a glance still tells you which source matched. Pixel size larger than sample-mode pins (e.g., `8` vs `6`) so the overlay reads as primary |
| **Hover label** | identical pattern to existing pointLabel handler — `meta.label \|\| meta.pid`, source badge color |
| **Click behavior** | identical to sample-mode click: `updateSampleCard()` + `pid` hash write. Single click handler can dispatch on `meta.type === 'searchResult'` vs `'sample'` |
| **Camera fit-to-bounds** | only fit-to-bounds when the result-set lat/lng extent **< 30° × 30°**. Otherwise: fly to top-1 result at altitude `200000` (same as today's first-result behavior). The 30° rule prevents a globally distributed result set from triggering a zoom-out to a near-globe view, which would be disorienting and wash out the cluster context |
| **Lifecycle** | populated immediately after results return; cleared on (a) search input cleared by user, (b) `?search=` removed from URL, (c) new search submitted (replaces the old overlay) |

### Result-set shape acceptance cases

Implementation must visually verify the four shape cases:

| case | description | expected behavior |
|------|-------------|-------------------|
| **zero** | `xyzzyqqqplugh` | no pins; side-panel says "No results"; cluster layer + facets unaffected; camera not flown |
| **one** | a `pid`-specific search that hits exactly one sample | one pin; fly-to-result at standard altitude; side panel shows the single result |
| **local-many** | `pottery Cyprus` (results clustered in one region) | up to 50 pins, lat/lng extent < 30°×30° → fit-to-bounds zoom |
| **global-many** | `basalt` (results spread across multiple continents) | up to 50 pins, extent ≥ 30°×30° → fly to top-1 at standard altitude; pins remain visible at multiple zoom levels via the cluster-overlay `scaleByDistance` |

### State-inventory addendum for (C)

The state contract grows a small amount:

| location                          | role                              | written by                             | read by                            | notes                                                  |
|-----------------------------------|-----------------------------------|----------------------------------------|------------------------------------|--------------------------------------------------------|
| `viewer.searchResultPoints`       | Cesium `PointPrimitiveCollection` for search-result pins | `zoomWatcher` (search handler) | mouse-move + click handlers | new collection; lifecycle tied to `?search=` non-empty |
| `viewer._searchResults` (Array)   | array of result rows currently rendered as pins | `zoomWatcher` (search handler) | future "fit-to-bounds" logic | optional cache; can be dropped if not needed |

URL/hash params are unchanged from (B). The DOM-as-state inventory is
unchanged.

**Note for parallel investigation.** A separate workstream (Codex, May 8) is
auditing full-text-search status, indexing options, and speed. The (C)
decision is intentionally orthogonal to the backend — *which UI surface
displays the matches* is independent of *how the matches are computed*. If
that investigation recommends switching the backend (e.g., from in-browser
ILIKE → static-Parquet inverted index → hosted-search service), (C) is
compatible with all of them.

### Light-path addendum: two-button scope selection ([#178](https://github.com/isamplesorg/isamplesorg.github.io/issues/178), 2026-05-08)

Hana's mockup ([Figma 213:394](https://www.figma.com/design/Nqkuqh3Z4aqVh0nmwUAgKg/iSamples-Wireframe-1.0?node-id=213-394))
proposed a two-button search UI: "Search Selected Areas" (viewport-scoped)
and "Search Entire World" (full-corpus). Implemented as a Light extension
of (C), not a revisit of the A/B/C decision:

- "Search Entire World" runs the existing (C) full-corpus side-panel
  lookup with result-pin overlay. Behavior unchanged from the contract above.
  SQL shape: CTE over `sample_facets_v2` → top-50 → `LEFT JOIN` to
  `samples_map_lite` for display coords (samples without coords still
  appear; lat/lng are null).
- "Search Selected Areas" runs the same text predicate but with a
  different SQL shape: `INNER JOIN` `samples_map_lite` inside the
  candidate selection, viewport `BETWEEN` predicate applied **before**
  `ORDER BY ... LIMIT 50`. This is critical — applying viewport after
  the global top-50 produces false zeroes (the global top-50 is
  concentrated in a few hot regions; a Sudan-area `pottery` query
  would return zero even though Sudan has plenty of pottery hits).
  Dateline-crossing is split into two longitude ranges.
- URL state gains `?search_scope=area|world`; default `world`, omitted
  from URL when default. Hydrated on boot; written by `persistSearchScope()`.
- Result-pin overlay still applies in both modes — pin coordinates
  reflect what was found, viewport-scope just narrows the candidate set.
- Auto-fly to the first result is suppressed in area mode (the user is
  already at the area they care about; flying would zoom in and disorient).
- Area mode requires coordinates by definition, so the `INNER JOIN`
  drops samples that have facets but no `samples_map_lite` row. World
  mode keeps them (via `LEFT JOIN`) since coord-less samples are still
  legitimate text matches.

A future Heavy revisit may rethink (A) global-filter semantics if usage
data shows users *expect* the map and facets to update with search.
That decision is deferred until #170-#172 land.

---

## 7. Facet-count contract

The cross-filter rule (codified by Codex in #158, restated here):

| dimension | counts respect it? | rationale |
|-----------|--------------------|-----------|
| other facet selections | **YES** | counts answer "if I add this value, how many samples would match all OTHER active filters plus this one"; that's the drill-out signal users want |
| viewport (camera bounds) | **NO** | counts are global. Viewport-scoped counts would couple facet UI to camera state, contradict the "facets describe the dataset" reading, and require re-querying on every camera change |
| `?search=` text query | **NO** | option (C); search renders a side panel + result-pin overlay, but does not alter facet counts |
| view mode (globe vs table) | **NO** | the same dataset underlies both; facet counts should not flip when the user toggles view |

Exposed via `applyFacetCounts(facetKey, countsMap)` (`:551-567`):

- `countsMap = null` ⇒ render the baseline counts from `viewer._baselineCounts`.
- `countsMap = Map<value, count>` ⇒ render the cross-filtered counts; missing
  keys render as `0` (and pick up the `.zero` class).

The "single active dim" fast path (`:1548-1584`) reads from a pre-aggregated
`cross_filter_url` parquet for instant response when exactly one facet value
is selected; the general path (`:1586-1604`) issues four parallel `GROUP BY`
queries against `facets_url`, one per dimension, each excluding its own
active values from the WHERE.

---

## 8. Out of scope

- Refactoring into modules (`urlState`, `globeView`, `facetCounts`, `tableView`,
  `sampleCard`, `search`). Once this contract is stable, the modular
  rewrite is a follow-up — not a prerequisite.
- Pure-OJS-reactive vs pure-imperative migration. We commit to imperative +
  URL-canonical here; the mechanical rewrite is separate.
- UX/copy items 1, 2, 3, 5, 6 from #163. They unblock against this contract
  but don't belong in it.
- Backend changes to the search query (FTS index, server-side service). See
  the parallel Codex investigation.

---

## 9. Acceptance signals

- ✅ Inventory tables populated from current `explorer.qmd`.
- ✅ Search-semantics decision recorded with rationale (option C, side-panel + result-pin overlay).
- ✅ Facet-count contract restated.
- ⏭ #163 items can now be re-scoped against this doc:
  - **#163 item 4** (zero search results + populated map looks broken) is
    resolved by option C, not by side-panel copy alone. Implementation
    must verify all four result-set shape cases (zero, one, local-many,
    global-many) per the table in §6.
  - **#163 item 6** (page in URL) gets a clear contract slot to plug into
    (a `page` query param participating in the same `writeQueryState`/
    hydration cycle as `view`).
  - The remaining items (1, 2, 3, 5, 7) are state-preserving UI fixes that
    don't perturb this contract.
