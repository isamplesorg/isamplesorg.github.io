# Pin-overlay implementation plan (option C, #164/#165 → #172 §7 track)

*2026-07-17, RY green-light "start now". Strategy: same playbook that shipped FTS
this morning — additive increment first, behavior change behind a flag, staging
verify, flip on confirmation.*

## Context deltas since the contract was written (May)

1. **Search is now a global filter** (#234 A1): `search_pids` semi-joins constrain
   table, points, facet counts. The contract's "facet counts exclude search" clause
   describes the *target* state, not today's. Users have 6+ weeks of habit with
   filter-everything behavior.
2. **Area/world scope already exists** (#178 landed): `?search_scope`, two-button UI,
   viewport-scoped SQL. Contract's "Light-path addendum" is DONE — do not rebuild.
3. **FTS is the default backend** (#335, today). Contract explicitly says (C) is
   backend-orthogonal — confirmed still true (both producers emit `search_pids`).

## Increments

### Inc 1 — additive pin overlay (no behavior removed) ← TODAY
After any search completes, render matching samples as a pin overlay per the
contract's non-negotiable rules:
- `viewer.searchResultPoints` = new `PointPrimitiveCollection`, added to
  `scene.primitives` AFTER `h3Points`/`samplePoints` (z-order rule)
- ≤ 50 pins (displayed result set), hollow-ring styling, `SOURCE_COLORS` palette,
  pixel size 8
- hover label + click → `updateSampleCard()` + pid hash write (dispatch on
  `meta.type === 'searchResult'`)
- lifecycle: populate on results; clear per SNAPSHOT SEMANTICS below
- camera (amended per Codex round-1 P1.5): Inc 1 ships only the cheap half —
  fly to the first *located* result @ 200000 (explicit null checks so 0° coords
  are valid), auto-fly suppressed in area scope (existing behavior). **Fit-to-
  bounds (the 30°×30° extent rule) is DEFERRED to Inc 2** — it is the only
  camera work not in Inc 1.
- global refiltering UNCHANGED in Inc 1 — pins are purely additive
- acceptance: the contract's four shape cases (zero / one / local-many /
  global-many). Inc 1 asserts pin *identity/count/replacement/clear* for all
  four; the **local-many fit-to-bounds ZOOM assertion is deferred to Inc 2**
  with the fit-to-bounds implementation (Inc 1 flies to the first located
  result in every non-area case instead)
- **lifecycle (amended, Codex round-1 P1.2 — SNAPSHOT SEMANTICS):** the pins are
  a snapshot of the *rendered results list* and reconcile with the LIST
  lifecycle, not with filter state. Cleared wherever the list is torn down
  (new/empty submit, described-by takeover, globe sample/cluster click). They
  deliberately PERSIST when the list persists stale (a source/facet toggle while
  a search is active updates #300 filtered surfaces but not the frozen list) —
  that staleness is pre-existing list behavior, documented, not a new pin bug.
  Known pre-existing incoherence left for a follow-up issue: a draft-input clear
  followed by a source/facet change makes `writeQueryState()` drop `search=`
  from the URL while the runtime filter (and thus list + pins) survive.
- **pin-count semantics (amended per review):** one pin per *located* displayed
  result (world scope legitimately returns coordinate-less rows — never coerce to
  (0,0)); panel reports displayed vs pinned counts when they differ; camera rules
  use the first *located* result
- **click parity (amended, Codex round-1 P1.3):** the sample-click ceremony
  (freshness token, card, selection/hash, detail hydration) is the shared
  `selectSearchResult()` helper with a preserve-results-list option; pin clicks
  use it — no shallow duplicate branch. Pin clicks get the FULL in-map card
  hydration (material / feature / specimen / thumbnail) by reusing
  `openInMapCardForSample()`, not a description-only fetch; the helper takes the
  caller's freshness token to avoid a double-bump
- **styling (amended):** carry `scaleByDistance` explicitly; use the bounded
  `POINT_DEPTH_TEST_DISTANCE` for `disableDepthTestDistance` (Codex round-1
  P1.1 — `Infinity` bleeds pins through the far side of the globe)

### Inc 2 — `?searchui=pin` mode (the latency win) ← behind flag
**Seam corrected per Codex plan review (P0):** skipping `applySearchFilterChange()`
is NOT sufficient — `window.__searchFilter.active` is consulted independently by
searchFilterSQL() (table/export/points/heatmap/facets), computeTargetMode(),
table messaging, heatmap cache keys, and camera moveEnd refreshes. The seam is a
single semantic predicate **`searchFiltersSurfaces()`** (false only for
`kind === 'text' && searchui === 'pin'`; concept/described-by filtering stays
global), used consistently by every consumer. Skipping the direct call then
becomes a latency optimization, not the correctness mechanism.
- expected effect: search response ≈ filter-build time (~1-5s cold) instead of
  +10-20s of surface refiltering — this is what makes #172 §7 winnable
- table/facets/clusters keep their pre-search state (facet counts stay
  search-independent, per original #158 contract)
- clear messaging in panel: "N matches pinned on globe" replaces "N of N in view"
- default stays current behavior until team confirms (Andrea/Eric habit risk);
  the eventual flip is a real change (tests/docs/rollback/telemetry), not 1 line —
  `searchui=pin|filter` recorded as a temporary rollout flag (deliberate,
  documented deviation from the "URL params unchanged" clause)
- URL: `searchui=pin` round-trips like `fts` param (state contract: no new hash state)

### Inc 3 — NOT in scope
Scope buttons (done), mockup-v1 sidebar mirror (#200 — parked per closure triage).

## Verification
- 4 acceptance cases on staging (fork Pages dispatch from branch, as this morning)
- e2e spec additions: pins count == min(50, results); pins cleared on clear;
  `?searchui=pin` skips refilter (assert facet counts unchanged after search)
- Codex loop: plan review (round 1 DONE 7/17 — P0 seam corrected, this doc amended)
  → implement → per-increment review rounds → LGTM gate
- honest sizing (Codex): Inc 1 ≈ 1–2 days · Inc 2 ≈ 2–4 days · staging ≈ 1 day

## Files
- `explorer.qmd`: viewer cell (~:773 area) for collection; `doSearch` result path
  for populate/clear; mouse/click handlers for pick dispatch; search-complete path
  for Inc 2 skip
- `tests/playwright/pin-overlay.spec.js` (new)
<!-- cc:2026.07.17 -->
