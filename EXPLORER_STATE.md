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
| `window.refreshSamplesTable` | `() => Promise<void>` | `:1238` | external (debug / Playwright) | not used by other cells; safe to keep or remove |

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
- Zooming behavior: today, search auto-flies to the first result. With
  result-pin overlay, the right behavior is probably **fit-to-bounds** of
  the result set (computeBoundingSphere of all pins) rather than zoom-to-
  first. UX call to confirm during implementation.

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
- ✅ Search-semantics decision recorded with rationale (option B).
- ✅ Facet-count contract restated.
- ⏭ #163 items can now be re-scoped against this doc:
  - **#163 item 4** (zero search results UX) is now framed as a
    side-panel-copy fix, not a search-semantics rethink.
  - **#163 item 6** (page in URL) gets a clear contract slot to plug into
    (a `page` query param participating in the same `writeQueryState`/
    hydration cycle as `view`).
  - The remaining items (1, 2, 3, 5, 7) are state-preserving UI fixes that
    don't perturb this contract.
