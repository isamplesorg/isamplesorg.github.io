/**
 * #300 verification [data]: filtered H3 clusters at world zoom.
 *
 * Runs against a LOCAL data mirror (dev_server.py on :8099) whose
 * samples_map_lite carries h3_res4/h3_res6, so window.__filteredClustersReady
 * becomes true and the feature ACTIVATES. (Production data lacks res4/res6, so
 * this can't run against data.isamples.org yet — that's the pending republish.)
 *
 * Pass DATA_BASE=http://localhost:8099 (default below).
 */
const { test, expect } = require('@playwright/test');

const DATA_BASE = process.env.DATA_BASE || 'http://localhost:8099';
const MATERIAL = 'https://w3id.org/isample/vocabulary/material/1.0/anyanthropogenicmaterial';
const WORLD_ALT = 18000000;   // world zoom, well above EXIT_POINT_ALT

function url(extraHash = '') {
  const qs = new URLSearchParams({ data_base: DATA_BASE, material: MATERIAL }).toString();
  return `/explorer.html?${qs}#v=1&lat=10.0000&lng=0.0000&alt=${WORLD_ALT}${extraHash}`;
}

// Read an OJS cell value (viewer, db, lite_url, facetFilterSQL, ...) the same way
// the existing helpers do.
const ojs = (page, name) =>
  page.evaluate((n) => window._ojs?.ojsConnector?.mainModule?.value(n), name);

test.setTimeout(180000);

test('(#300) [data] broad facet at world zoom renders FILTERED clusters, not point mode', async ({ page }) => {
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto(url());

  // 1. Readiness preflight resolves true (lite has res4/res6).
  await expect.poll(() => page.evaluate(() => window.__filteredClustersReady === true),
    { timeout: 120000, message: 'filteredClustersReady should become true with res46 lite' }).toBe(true);

  // 2. The cluster layer becomes FILTERED at world zoom (the #300 win). NB:
  //    _globeState.mode DEFAULTS to 'cluster' at init, so polling mode alone is
  //    not meaningful — the authoritative signal is _clusterFilterSig.kind ===
  //    'filtered', set only when loadRes actually aggregated the filtered set.
  await expect.poll(() => page.evaluate(async () => {
    const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
    try { return JSON.parse(v?._clusterFilterSig || '{}').kind; } catch { return null; }
  }), { timeout: 120000, message: 'facet at world zoom should load FILTERED clusters' }).toBe('filtered');

  // 3. Still in cluster mode (not forced point #267) and cells actually rendered.
  const { mode, clusterCount } = await page.evaluate(async () => {
    const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
    return { mode: v?._globeState?.mode, clusterCount: v?._clusterData?.length || 0 };
  });
  expect(mode, 'cluster mode, not forced point').toBe('cluster');
  expect(clusterCount, 'filtered clusters rendered').toBeGreaterThan(50);

  // 4. COUNT CONSERVATION: the filtered cluster sample_count sum equals an
  //    independent filtered COUNT(*) via the same facetFilterSQL masks predicate.
  const { clusterSum, directCount } = await page.evaluate(async () => {
    const mm = window._ojs.ojsConnector.mainModule;
    const v = await mm.value('viewer');
    const db = await mm.value('db');
    const lite = await mm.value('lite_url');
    const facetFilterSQL = await mm.value('facetFilterSQL');
    const sum = v._clusterData.reduce((a, r) => a + Number(r.sample_count), 0);
    const r = await db.query(`SELECT COUNT(*)::INTEGER AS n FROM read_parquet('${lite}') WHERE 1=1${facetFilterSQL()}`);
    const direct = Number(Array.from(r)[0].n);
    return { clusterSum: sum, directCount: direct };
  });
  expect(clusterSum, 'cluster sum > 0').toBeGreaterThan(0);
  expect(directCount, 'filtered cluster sum == independent filtered count').toBe(clusterSum);

  // 5. No uncaught console errors during the filtered-cluster render. Exclude
  //    known-benign noise: favicon/Cesium-ion/ResizeObserver/sourcemap, and the
  //    listings.json 404 (Quarto issue #295 — present in production too, unrelated
  //    to #300). "Failed to load resource" is the generic Chromium text for these.
  const realErrors = errors.filter(e =>
    !/favicon|cesium ion|ResizeObserver|sourcemap|listings\.json|Failed to load resource/i.test(e));
  expect(realErrors, `console errors: ${realErrors.join(' | ')}`).toHaveLength(0);
});

test('(#300) [data] zoom-in promotes filtered clusters to individual point mode', async ({ page }) => {
  await page.goto(url());
  await expect.poll(() => page.evaluate(() => window.__filteredClustersReady === true), { timeout: 120000 }).toBe(true);
  await expect.poll(() => page.evaluate(async () => {
    const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
    return v?._globeState?.mode;
  }), { timeout: 120000 }).toBe('cluster');

  // Fly to a low altitude (below ENTER_POINT_ALT = 120 km). Use a real animated
  // flight with a completion callback so Cesium raises moveEnd (a duration:0 jump
  // may not fire the camera event the explorer's handler needs).
  await page.evaluate(async () => {
    const v = await window._ojs.ojsConnector.mainModule.value('viewer');
    await new Promise(resolve => {
      v.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(0, 40, 60000),
        duration: 0.4, complete: resolve, cancel: resolve,
      });
    });
  });
  // Facet still active + altitude < ENTER → computeTargetMode → point.
  await expect.poll(() => page.evaluate(async () => {
    const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
    return v?._globeState?.mode;
  }), { timeout: 120000, message: 'zoom-in with facet should drop to point mode' }).toBe('point');
});
