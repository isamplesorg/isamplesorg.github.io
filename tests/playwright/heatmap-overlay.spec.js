const { test, expect } = require('@playwright/test');
const { explorerUrl } = require('./helpers/url');

const CYPRUS_HASH = '#v=1&lat=35&lng=33&alt=500000';

test.describe('Heatmap overlay (#233 phase 1)', () => {
  test.setTimeout(180000);

  async function openExplorer(page) {
    await page.goto(explorerUrl(CYPRUS_HASH), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await page.waitForFunction(() => !!window._ojs?.ojsConnector?.mainModule, null, { timeout: 60000 });
    await page.evaluate(async () => {
      return await window._ojs.ojsConnector.mainModule.value('zoomWatcher');
    });
  }

  async function waitForFacetCheckboxes(page) {
    await page.waitForFunction(
      () => document.querySelectorAll('#materialFilterBody input[type="checkbox"]').length > 0,
      null,
      { timeout: 60000 }
    );
  }

  async function heatmapState(page) {
    await page.waitForFunction(() => !!window._ojs?.ojsConnector?.mainModule, null, { timeout: 60000 });
    return await page.evaluate(() => {
      return window._ojs.ojsConnector.mainModule.value('viewer').then((v) => {
        const state = v?._heatmapOverlay || {};
        return {
          enabled: !!state.enabled,
          hasLayer: !!state.layer,
          layerShown: state.layer ? state.layer.show !== false : false,
          lastRefreshAt: state.lastRefreshAt || 0,
          lastPointCount: state.lastPointCount || 0,
          lastImageHash: state.lastImageHash || null,
          status: document.getElementById('heatmapStatus')?.textContent || '',
        };
      });
    });
  }

  async function enableHeatmap(page) {
    await page.locator('#heatmapToggle').check();
    await expect.poll(async () => {
      const state = await heatmapState(page);
      return state.enabled && state.hasLayer && state.layerShown;
    }, {
      timeout: 90000,
      intervals: [250, 500, 1000],
    }).toBeTruthy();
  }

  // Reads the live `.show` flags off the two marker collections so a test
  // can assert mutual exclusion with the heatmap overlay (#233 phase 3).
  async function markerVisibility(page) {
    return await page.evaluate(() => {
      return window._ojs.ojsConnector.mainModule.value('viewer').then((v) => ({
        clusterShown: v?.h3Points?.show === true,
        pointShown: v?.samplePoints?.show === true,
        mode: v?._globeState?.mode || null,
      }));
    });
  }

  test('heatmap toggle exists', async ({ page }) => {
    await openExplorer(page);
    await expect(page.locator('#heatmapToggle')).toBeVisible();
  });

  test('phase 3: enabling heatmap hides cluster dots; disabling restores them', async ({ page }) => {
    // #233 phase 3: heatmap is mutually exclusive with the marker layers.
    // The dots-vs-hotspots disagreement RY flagged 2026-05-27 came from
    // both layers painting at once. At the Cyprus hash (alt=500km, well
    // above ENTER_POINT_ALT=120km) the explorer is in cluster mode, so
    // h3Points are the visible markers.
    await openExplorer(page);

    const before = await markerVisibility(page);
    expect(before.mode).toBe('cluster');
    expect(before.clusterShown).toBe(true);

    await enableHeatmap(page);
    await expect.poll(async () => (await markerVisibility(page)).clusterShown, {
      timeout: 30000,
      intervals: [100, 250, 500],
    }).toBe(false);
    // Sample points stay hidden too (they are point-mode only).
    expect((await markerVisibility(page)).pointShown).toBe(false);

    await page.locator('#heatmapToggle').uncheck();
    await expect.poll(async () => (await markerVisibility(page)).clusterShown, {
      timeout: 30000,
      intervals: [100, 250, 500],
    }).toBe(true);
  });

  test('phase 3: in point mode, heatmap hides sample points; off restores them', async ({ page }) => {
    // Codex review of #233 phase 3: the cluster test above covers the
    // h3Points half; this covers the samplePoints half. Boot deep into a
    // dense area (alt=8km < ENTER_POINT_ALT=120km) so boot enters point
    // mode. Cold-cache point entry fetches the res8 + samples parquet, so
    // allow generous time — mirrors the explorer-helper point-mode specs.
    const POINT_HASH = '#v=1&lat=35&lng=33&alt=8000';
    await page.goto(explorerUrl(POINT_HASH), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await page.waitForFunction(() => !!window._ojs?.ojsConnector?.mainModule, null, { timeout: 60000 });
    // Wait for boot to settle into point mode.
    await expect.poll(async () => (await markerVisibility(page)).mode, {
      timeout: 150000,
      intervals: [500, 1000, 2000],
    }).toBe('point');
    // Point mode, heatmap off: sample points shown, cluster dots hidden.
    await expect.poll(async () => (await markerVisibility(page)).pointShown, {
      timeout: 30000,
      intervals: [250, 500, 1000],
    }).toBe(true);
    expect((await markerVisibility(page)).clusterShown).toBe(false);

    // Heatmap on: both marker collections hidden.
    await enableHeatmap(page);
    await expect.poll(async () => (await markerVisibility(page)).pointShown, {
      timeout: 30000,
      intervals: [100, 250, 500],
    }).toBe(false);
    expect((await markerVisibility(page)).clusterShown).toBe(false);

    // Heatmap off: sample points restored (still point mode).
    await page.locator('#heatmapToggle').uncheck();
    await expect.poll(async () => (await markerVisibility(page)).pointShown, {
      timeout: 30000,
      intervals: [100, 250, 500],
    }).toBe(true);
  });

  test('phase 3: heatmap on hides the #facetNote apology', async ({ page }) => {
    // #233: with the heatmap on, the facet note ("filters apply at sample
    // zoom level") is a lie — the heatmap shows filtered density directly.
    // It must be hidden whenever a facet filter is active AND heatmap is on.
    await openExplorer(page);
    await waitForFacetCheckboxes(page);

    // Activate a material facet so the note would otherwise show in cluster
    // mode (visible ⇔ active ∧ cluster ∧ heatmap-off).
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[type="checkbox"]');
      if (cb) { cb.checked = true; cb.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await expect(page.locator('#facetNote')).toBeVisible();

    await enableHeatmap(page);
    await expect(page.locator('#facetNote')).toBeHidden();

    await page.locator('#heatmapToggle').uncheck();
    await expect(page.locator('#facetNote')).toBeVisible();
  });

  test('toggle on renders a visible heatmap layer', async ({ page }) => {
    await openExplorer(page);
    await enableHeatmap(page);
    const state = await heatmapState(page);
    expect(state.lastRefreshAt).toBeGreaterThan(0);
    expect(state.lastPointCount).toBeGreaterThan(0);
  });

  test('toggle off clears the heatmap layer', async ({ page }) => {
    await openExplorer(page);
    await enableHeatmap(page);
    await page.locator('#heatmapToggle').uncheck();
    await expect.poll(async () => {
      const state = await heatmapState(page);
      return !state.enabled && !state.hasLayer;
    }, {
      timeout: 30000,
      intervals: [100, 250, 500],
    }).toBeTruthy();
  });

  test('source and material filter changes regenerate the heatmap', async ({ page }) => {
    await openExplorer(page);
    await waitForFacetCheckboxes(page);
    await enableHeatmap(page);

    const first = await heatmapState(page);
    await page.evaluate(() => {
      const cb = document.querySelector('#sourceFilter input[value="SMITHSONIAN"]');
      cb.checked = false;
      cb.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // Codex round-1 review of #240: assert on the rendered IMAGE changing,
    // not just the refresh timestamp. A timestamp bump can fire from the
    // error path too; an image-hash change proves a new layer was painted.
    await expect.poll(async () => (await heatmapState(page)).lastImageHash, {
      timeout: 90000,
      intervals: [250, 500, 1000],
    }).not.toBe(first.lastImageHash);

    const second = await heatmapState(page);
    const material = await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[type="checkbox"]');
      if (!cb) return null;
      cb.checked = true;
      cb.dispatchEvent(new Event('change', { bubbles: true }));
      return cb.value;
    });
    expect(material).toBeTruthy();
    await expect.poll(async () => (await heatmapState(page)).lastImageHash, {
      timeout: 90000,
      intervals: [250, 500, 1000],
    }).not.toBe(second.lastImageHash);
  });

  test('heatmap=1 in URL hash boots with overlay on (round-trip)', async ({ page }) => {
    // Reported by RY 2026-05-27 on PR #240 staging: "Copy Link to Current
    // View" was losing the heatmap-on state. URL now encodes `heatmap=1`
    // and boot hydration flips the toggle + dispatches change event.
    await page.goto(explorerUrl(CYPRUS_HASH + '&heatmap=1'), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await page.waitForFunction(() => !!window._ojs?.ojsConnector?.mainModule, null, { timeout: 60000 });
    await expect.poll(async () => {
      const state = await heatmapState(page);
      return state.enabled && state.hasLayer && state.lastPointCount > 0;
    }, {
      timeout: 90000,
      intervals: [250, 500, 1000],
    }).toBeTruthy();
    // Also assert the toggle DOM reflects the hydrated state.
    await expect(page.locator('#heatmapToggle')).toBeChecked();
    // #233 phase 3: a hydrated heatmap=1 boot must also hide the markers —
    // the toggle's change handler (dispatched during boot) routes through
    // applyLayerVisibility(). Cyprus is cluster mode, so h3Points hidden.
    await expect.poll(async () => (await markerVisibility(page)).clusterShown, {
      timeout: 30000,
      intervals: [250, 500, 1000],
    }).toBe(false);
  });

  test('world view counts every sample (no LIMIT cap — phase 1.5)', async ({ page }) => {
    // PR #241 (SQL pre-aggregation) removed the 100k LIMIT that PR #240
    // had. This test pins that property: world view at alt=15Mkm should
    // see > 100k samples (true count is ~6M) AND `capped` must be false.
    // Codex round-1 review of #241 suggested this assertion to lock in
    // the architectural promise that LIMIT is gone for good.
    const WORLD_HASH = '#v=1&lat=20&lng=0&alt=15000000';
    await page.goto(explorerUrl(WORLD_HASH + '&heatmap=1'), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await page.waitForFunction(() => !!window._ojs?.ojsConnector?.mainModule, null, { timeout: 60000 });
    await expect.poll(async () => {
      const state = await heatmapState(page);
      return state.enabled && state.hasLayer && state.lastPointCount > 0;
    }, {
      timeout: 120000,
      intervals: [500, 1000, 2000],
    }).toBeTruthy();
    const state = await heatmapState(page);
    expect(state.lastPointCount).toBeGreaterThan(100000);
    // Codex round-2 polish: assert the raw `capped` field value (must be
    // strictly false), not just "not-true" (which would also pass for
    // undefined / null / etc).
    const cappedRaw = await page.evaluate(async () => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      return v?._heatmapOverlay?.capped;
    });
    expect(cappedRaw).toBe(false);
  });

  // Helper: shift the camera by a longitude delta (degrees), keeping lat/
  // height, and return the resulting padded-viewport span so the test can
  // reason about the tolerance threshold.
  async function nudgeLongitude(page, deltaDeg) {
    await page.evaluate(async (d) => {
      const Cesium = window.Cesium;
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      const cc = v.camera.positionCartographic;
      v.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(
          Cesium.Math.toDegrees(cc.longitude) + d,
          Cesium.Math.toDegrees(cc.latitude),
          cc.height),
      });
    }, deltaDeg);
  }

  test('loop fix: sub-threshold viewport jitter does NOT re-render; a real move does', async ({ page }) => {
    // #233 loop fix (RY 2026-05-28): with Cesium World Terrain on, the
    // camera height keeps settling for a beat after a move, firing moveEnd
    // with a slightly-shifted computeViewRectangle. The old exact-key
    // dedupe (toFixed(4)) let that jitter through → re-render → terrain
    // nudge → moveEnd → … a self-sustaining refresh loop. The tolerance
    // dedupe ignores view changes under 2% of span. This test simulates
    // the two ends of that spectrum: a tiny nudge (jitter-class, must be
    // ignored) and a large move (real, must re-render).
    await openExplorer(page);
    await enableHeatmap(page);
    const first = await heatmapState(page);
    expect(first.lastRefreshAt).toBeGreaterThan(0);

    const skipsAndLng = async () => page.evaluate(async () => {
      const Cesium = window.Cesium;
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      return { skips: v._heatmapSkips || 0, lng: Cesium.Math.toDegrees(v.camera.positionCartographic.longitude) };
    });
    const before = await skipsAndLng();

    // Tiny nudge (~0.01° on a multi-degree span ≪ 2% tolerance). Fires
    // moveEnd but must NOT bump lastRefreshAt. Crucially we ALSO assert the
    // skip counter incremented — that PROVES a real moveEnd reached the
    // tolerance branch and was skipped, rather than the negative assertion
    // passing vacuously because no moveEnd fired (Codex review 2026-05-28).
    await nudgeLongitude(page, 0.01);
    await expect.poll(async () => (await skipsAndLng()).skips, {
      timeout: 10000,
      intervals: [100, 250, 500],
    }).toBeGreaterThan(before.skips);
    const afterJitter = await skipsAndLng();
    // The camera really moved (so computeViewRectangle differed)…
    expect(Math.abs(afterJitter.lng - before.lng)).toBeGreaterThan(0.005);
    // …yet no re-render happened, and the overlay is still present.
    const jitterState = await heatmapState(page);
    expect(jitterState.lastRefreshAt).toBe(first.lastRefreshAt);
    expect(jitterState.hasLayer).toBe(true);

    // Real move (~6°, far beyond tolerance) must trigger a fresh render.
    await nudgeLongitude(page, 6);
    await expect.poll(async () => (await heatmapState(page)).lastRefreshAt, {
      timeout: 90000,
      intervals: [250, 500, 1000],
    }).toBeGreaterThan(first.lastRefreshAt);
  });
});
