# #300 browser design — filtered H3 clusters at world zoom

Goal: when a **facet** filter is active and the camera is zoomed out (above
`EXIT_POINT_ALT`), render an h3-clustered view of the **filtered** set instead of
forcing raw capped point mode (#267). Zoom-in still drops to individual dots.
Search is OUT of scope (stays point-mode). Foundation: #293 masks make filtered
h3 aggregation ~25× faster; build now adds `h3_res4/h3_res6` to `samples_map_lite`.

## Components

### 1. Readiness preflight (new ojs cell, mirrors `nodeBitsReady`)
```js
filteredClustersReady = {
    window.__filteredClustersReady = false;
    try {
        await db.query(`SELECT h3_res4, h3_res6 FROM read_parquet('${lite_url}') LIMIT 1`);
        window.__filteredClustersReady = true; return true;
    } catch (err) {
        console.warn('lite lacks h3_res4/res6; #300 filtered clusters disabled (point fallback):', err);
        return false;
    }
}
```
Hard requirement is ONLY that lite has res4/res6. (masks readiness is orthogonal:
`facetFilterSQL()` already self-falls-back to the membership scan when masks
absent — affects speed, not correctness.) Safe to ship before the lite republish:
flag stays false → today's point-mode behavior.

### 2. `computeTargetMode(alt)` rule change (was: any filter → point)
```js
const computeTargetMode = (alt) => {
    if (searchIsActive()) return 'point';                         // search out of scope
    if (hasFacetFilters() && !window.__filteredClustersReady) return 'point'; // pre-republish / preflight pending
    if (alt < ENTER_POINT_ALT) return 'point';
    if (alt > EXIT_POINT_ALT) return 'cluster';
    return getMode();                                              // hysteresis band
};
```
Net: once ready, facets use the SAME altitude hysteresis as the unfiltered case
(loadRes makes the clusters filter-aware). Flicker-safe (keeps ENTER/EXIT band).
`filtersForcePoint()` stays = `searchIsActive() || hasFacetFilters()` and is still
correct at the remaining call sites (see §5).

### 3. `loadRes` becomes filter-aware (one branch; everything else identical)
```js
const wantFiltered = hasFacetFilters() && window.__filteredClustersReady;
const data = wantFiltered
    ? await db.query(filteredClusterSQL(res))
    : await db.query(`SELECT CAST(h3_cell AS VARCHAR) AS h3_cell_dec, sample_count,
        center_lat, center_lng, dominant_source, source_count
        FROM read_parquet('${url}') WHERE 1=1${sourceFilterSQL('dominant_source')}`);
```
`filteredClusterSQL(res)` (off lite, masks-backed) returns the EXACT same columns:
```sql
WITH base AS (
  SELECT h3_res{res} AS cell, source, latitude, longitude
  FROM read_parquet('${lite_url}')
  WHERE h3_res{res} IS NOT NULL ${sourceFilterSQL('source')} ${facetFilterSQL()}),
sc AS (SELECT cell, source, COUNT(*) c FROM base GROUP BY cell, source),
dom AS (SELECT cell, source AS dominant_source,
        ROW_NUMBER() OVER (PARTITION BY cell ORDER BY c DESC, source ASC) rn FROM sc),
agg AS (SELECT cell, COUNT(*) sample_count, ROUND(AVG(latitude),6) center_lat,
        ROUND(AVG(longitude),6) center_lng, COUNT(DISTINCT source) source_count
        FROM base GROUP BY cell)
SELECT CAST(agg.cell AS VARCHAR) AS h3_cell_dec, agg.sample_count, agg.center_lat,
       agg.center_lng, dom.dominant_source, agg.source_count
FROM agg JOIN dom ON dom.cell = agg.cell AND dom.rn = 1
```
Same `loadResGen` generation guard, render loop, `_clusterData`/`_clusterTotal`
cache, and "Samples in View" stat — all unchanged. The exact in-view COUNT comes
from `countInViewport(_clusterData)` as today (now over filtered cells).

### 4. The stale-cluster reload problem (the main risk)
The camera `targetMode==='cluster'` branch only reloads when `target !== currentRes`.
On point→cluster (zoom out with a facet active), `currentRes` may already equal
`target`, so it would SKIP loadRes and show stale (unfiltered or
previously-filtered) clusters. Also, toggling a facet while already in cluster
mode at a fixed altitude is `target === currentRes` → no reload.

Fix: track the filter signature the current `_clusterData` was built under and
reload when it differs. Add:
```js
viewer._clusterFilterSig = null;                  // set in loadRes after a successful load
function currentFilterSig() {
    return (hasFacetFilters() && window.__filteredClustersReady)
        ? JSON.stringify({ f: facetFilterSQL(), s: sourceFilterSQL('source') }) : null;
}
```
- In `loadRes` success: `viewer._clusterFilterSig = currentFilterSig();`
- Camera `cluster` branch + the "already cluster, check resolution" branch: reload
  when `target !== currentRes || viewer._clusterFilterSig !== currentFilterSig()`.

### 5. Handlers (`handleFacetFilterChange`, `applySearchFilterChange`)
Both currently force point when a filter is active. Replace the force-point block
with a reconcile that honors `computeTargetMode`:
```js
async function reconcileGlobeForFilters() {
    const h = viewer.camera.positionCartographic.height;
    if (computeTargetMode(h) === 'point') {
        if (getMode() !== 'point') await enterPointMode(false);
        else await loadViewportSamples();                 // refilter the dots
    } else { // cluster
        if (getMode() === 'point') exitPointMode(false);
        const res = h > 3000000 ? 4 : h > 300000 ? 6 : 8;
        await loadRes(res, { 4: h3_res4_url, 6: h3_res6_url, 8: h3_res8_url }[res]); // filtered (incl. resig change)
    }
}
```
- `handleFacetFilterChange`: call `reconcileGlobeForFilters()` (replaces the
  hasFacetFilters() force-point + the facet-cleared exit logic — computeTargetMode
  subsumes both: cleared facet + search inactive + high alt → cluster; etc.)
- `applySearchFilterChange`: same. Note clearing SEARCH while a facet remains must
  now land in filtered clusters at high alt — `reconcileGlobeForFilters` handles it
  because computeTargetMode sees only the facet (search inactive → not forced).

### 6. Deep-link restore (wantsPoint, ~4538)
Today: `filtersForcePoint() || s.mode==='point' || (s.alt<ENTER)`. For a
facet-filtered world-zoom deep link this forces point (the slow case #300 fixes).
Change to compute from restored altitude and load filtered clusters when cluster:
```js
const restoredAlt = s.alt ?? viewer.camera.positionCartographic.height;
const target = s.mode === 'point' ? 'point' : computeTargetMode(restoredAlt);
if (target === 'point' && getMode() !== 'point') await enterPointMode(false);
else if (target === 'cluster') {
    if (getMode() === 'point') exitPointMode(false);
    const res = restoredAlt > 3000000 ? 4 : restoredAlt > 300000 ? 6 : 8;
    await loadRes(res, {4:h3_res4_url,6:h3_res6_url,8:h3_res8_url}[res]);
}
```
(`s.mode==='point'` still wins to honor an explicitly saved point view.)

## Codex review integrated (2026-06-18) — implementation spec of record

Staged in 3 commits within the PR:
- **C1 (dormant infra):** `filteredClustersReady` preflight cell; `filteredClusterSQL(res)`
  with `COUNT(*)::INTEGER`/`COUNT(DISTINCT source)::INTEGER` casts (P0.1); semantic
  `desiredClusterSig()` = `{kind, sources(always), material, context, objectType}`
  (P1.3, NOT sql text); `loadRes` filter-aware with **snapshot sig captured before
  the await**, re-checked after (`gen !== loadResGen || sig !== desiredClusterSig()`)
  (P0.2); set `viewer._clusterFilterSig = sig` on success; init the sig in phase1
  (P1.3). Dormant because computeTargetMode still forces point until C2.
- **C2 (activation):** `computeTargetMode(alt, latch = getMode())` — add restored-latch
  param (P1.7); rule = search→point, facet&&!ready→point, else ENTER/EXIT hysteresis.
  `reconcileGlobeForFilters()` used by both filter-change handlers; every `loadRes`
  caller captures `applied` + chases `tryEnterPointModeIfNeeded()` and invalidates
  pending cluster loads when target flips to point (P1.4). camera `cluster` branches
  reload on `target !== currentRes || viewer._clusterFilterSig !== desiredClusterSig()`
  (stale-cluster). `moveEnd` gate (4334) → `computeTargetMode(h)` + sig reload (P1.5).
  Readiness→reconcile hook (P1.9). Fail-safe: stay in point / hide stale clusters if a
  filtered load fails (P1.10).
- **C3 (coherence):** deep-link restore (4538) with latch + filtered cluster load +
  `isStale()` before mode mutation and after each await + cluster-gen invalidation on
  newer hashchange (P1.6/P1.7); boot facet block (~5771) → computeTargetMode-aware
  (P1.7); `fetchClusterByH3()` (4365) filter-aware single-cell aggregation + revalidate
  `selectedH3` after facet changes (P1.8); `syncFacetNote()` message no longer claims
  "only at neighborhood zoom" when filtered clusters active (P1.10).

Out of scope (pre-existing, documented): `AVG(longitude)` antimeridian skew and the
cell-center "Samples in View" inexactness — both already in the shipped summaries.

## Open questions for review
1. Is making `loadRes` filter-aware (vs a separate `loadFilteredClusters`) the
   right call? It reuses the generation guard / render / cache / stats exactly,
   but couples two data sources in one fn.
2. `_clusterFilterSig` approach for the stale-cluster reload — correct & sufficient?
   Any path that loads clusters without setting the sig, or compares it wrong?
3. Deep-link: is loading filtered clusters in the restore `setTimeout` safe wrt the
   `isStale()` / freshness-token races in that handler, and the suppress-hash gate?
4. Should `handleFacetFilterChange`'s existing `await new Promise(r=>setTimeout(r,300))`
   and busy-flag structure be preserved as-is around the new reconcile?
5. Any hysteresis/latching regression from facets now using the ENTER/EXIT band
   instead of always-point? (Esp. #234 A1/C3 search-latch interactions.)
6. `filteredClusterSQL` correctness: `dominant_source` recomputed over the FILTERED
   subset (vs summary's all-sample dominant) — intended and fine?
