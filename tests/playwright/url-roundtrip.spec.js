/**
 * Explorer URL state round-trip regressions (closes #209).
 *
 * CI-safe spec set extracted from `url_roundtrip_investigation.js` (which
 * remains as a manual diagnostic targeting the live deploy). These tests
 * run against `localhost:5860` (Quarto preview) and cover the URL state
 * contract slices fixed in PRs #203, #205, #210, #212. They don't try
 * to drive cold-cache deep-links — that's slow and network-sensitive and
 * stays in the investigation harness.
 *
 * Coverage matrix:
 *   - Point-mode deep-link with `mode=point` (Bug B fix from #203)
 *   - Low-alt deep-link WITHOUT `mode=point` (#207 item 4)
 *   - Sub-threshold pan settles via `moveEnd` (#205)
 *   - Round-trip across contexts: copy URL, paste in fresh context,
 *     same camera/mode (#203/#205/#207 combined)
 *   - `h3` hashchange null-result clears `_globeState.selectedH3`
 *     (#207 item 6)
 *
 * Search-result row click selection (#207 item 8) needs working FTS
 * data; deferred to a manual smoke or a separate spec once a fixture
 * dataset is available.
 */

const { test, expect } = require('@playwright/test');

const EXPLORER_PATH = '/explorer.html';

// Cyprus / Polis — confirmed dense region (~23k samples), used in #206/#210.
const LAT = 34.9957;
const LNG = 33.6798;
const ALT_POINT = 8000;    // < ENTER_POINT_ALT = 120000 → point mode
const ALT_POINT_DEEP = 62054;
const ALT_CLUSTER = 500000;
const ENTER_POINT_ALT = 120000;

/** Wait until `viewer._globeState.mode` equals `expected`.
 *  Cold-cache point-mode boot can take 60–90s per #190; allow 3 minutes. */
async function waitForMode(page, expected, timeoutMs = 180000) {
  await page.waitForFunction(
    async (expectedMode) => {
      try {
        const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
        return v?._globeState?.mode === expectedMode;
      } catch { return false; }
    },
    expected,
    { timeout: timeoutMs }
  );
}

/** Wait until `loadViewportSamples` has settled into the point-mode done message. */
async function waitForPointModeSettled(page, timeoutMs = 120000) {
  await page.waitForFunction(
    () => {
      const msg = document.getElementById('phaseMsg')?.textContent || '';
      return msg.includes('Click one for details');
    },
    null,
    { timeout: timeoutMs }
  );
}

/** Snapshot camera + mode + selection + URL hash from the live page. */
async function snapshot(page) {
  return await page.evaluate(async () => {
    const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
    const carto = v?.camera?.positionCartographic;
    if (!carto) return null;
    return {
      url: location.href,
      hash: location.hash,
      lat: Cesium.Math.toDegrees(carto.latitude),
      lng: Cesium.Math.toDegrees(carto.longitude),
      alt: carto.height,
      mode: v._globeState.mode,
      selectedPid: v._globeState.selectedPid || null,
      selectedH3: v._globeState.selectedH3 || null,
    };
  });
}

// ---- Tests ----------------------------------------------------------------

test.describe('Explorer URL state round-trip (issue #209)', () => {
  // Cold-cache point-mode deep-link can take 60–90s per #190; round-trip
  // tests open multiple fresh contexts, each paying the cache cost.
  test.setTimeout(360000);


  test('deep-link with mode=point enters point mode (Bug B from #203)', async ({ page }) => {
    const url = `${EXPLORER_PATH}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_POINT_DEEP}&mode=point`;
    await page.goto(url);
    await waitForMode(page, 'point');
    await waitForPointModeSettled(page);
    const s = await snapshot(page);
    expect(s.mode).toBe('point');
    expect(Math.abs(s.alt - ALT_POINT_DEEP)).toBeLessThan(100);
  });

  test('deep-link with low altitude AND no mode=point still enters point mode (#207 item 4)', async ({ page }) => {
    // No `mode=point` in URL. Boot should enter point based on altitude alone.
    const url = `${EXPLORER_PATH}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_POINT}`;
    await page.goto(url);
    // Wait for the settled point-mode done message — more reliable than
    // waitForMode alone, which can match a transient mode flip during boot
    // (the dual-mode-state anomaly being fixed in #208).
    await waitForPointModeSettled(page);
    const s = await snapshot(page);
    expect(s.mode).toBe('point');
    expect(s.alt).toBeLessThan(ENTER_POINT_ALT);
  });

  test('sub-threshold pan updates URL hash via moveEnd (#205)', async ({ page }) => {
    // Start at a settled point-mode view.
    const url = `${EXPLORER_PATH}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_POINT_DEEP}&mode=point`;
    await page.goto(url);
    await waitForMode(page, 'point');
    await waitForPointModeSettled(page);
    const before = await snapshot(page);

    // Programmatically drive a SMALL pan (Δlat ≈ 0.02°). The pan is small
    // enough that `camera.percentageChanged = 0.1` may not raise
    // `camera.changed`, but `moveEnd` always fires once on flight complete.
    const newLat = LAT + 0.02;
    const newLng = LNG + 0.02;
    await page.evaluate(async ({ lat, lng, alt }) => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      v.scene.requestRenderMode = false;  // keep render loop alive in headless
      v.camera.cancelFlight();
      v.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(lng, lat, alt),
        duration: 1.0,
      });
    }, { lat: newLat, lng: newLng, alt: ALT_POINT_DEEP });

    // Wait flight duration + moveEnd debounce
    await page.waitForTimeout(2500);

    const after = await snapshot(page);
    // URL hash must reflect the new lat/lng — Bug A residual fixed by #205.
    const params = new URLSearchParams(after.hash.slice(1));
    const urlLat = parseFloat(params.get('lat'));
    const urlLng = parseFloat(params.get('lng'));
    expect(Math.abs(urlLat - newLat)).toBeLessThan(0.001);
    expect(Math.abs(urlLng - newLng)).toBeLessThan(0.001);
  });

  test('URL round-trips across browser contexts (#203 + #205 combined)', async ({ browser }) => {
    // Context A: navigate, settle, programmatically pan + zoom, capture URL.
    const ctxA = await browser.newContext();
    const pageA = await ctxA.newPage();
    await pageA.goto(`${EXPLORER_PATH}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_POINT_DEEP}&mode=point`);
    await waitForMode(pageA, 'point');
    await waitForPointModeSettled(pageA);

    const newLat = LAT + 0.01;
    const newLng = LNG - 0.01;
    const newAlt = 9500;  // still below ENTER_POINT_ALT
    await pageA.evaluate(async ({ lat, lng, alt }) => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      v.scene.requestRenderMode = false;
      v.camera.cancelFlight();
      v.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(lng, lat, alt),
        duration: 1.0,
      });
    }, { lat: newLat, lng: newLng, alt: newAlt });
    await pageA.waitForTimeout(2500);

    const snapA = await snapshot(pageA);
    expect(snapA.mode).toBe('point');

    // Context B: open the captured URL, verify camera/mode round-trip.
    const ctxB = await browser.newContext();
    const pageB = await ctxB.newPage();
    await pageB.goto(snapA.url);
    await waitForPointModeSettled(pageB);
    const snapB = await snapshot(pageB);

    expect(Math.abs(snapA.lat - snapB.lat)).toBeLessThan(0.001);
    expect(Math.abs(snapA.lng - snapB.lng)).toBeLessThan(0.001);
    expect(Math.abs(snapA.alt - snapB.alt)).toBeLessThan(50);
    expect(snapB.mode).toBe('point');

    await ctxA.close();
    await ctxB.close();
  });

  test('h3 hashchange with invalid cell clears selectedH3 (#207 item 6)', async ({ page }) => {
    // Boot at a cluster altitude with a deliberately invalid h3.
    const invalidH3 = '0deadbeefffffff';  // not a real h3 cell
    await page.goto(`${EXPLORER_PATH}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_CLUSTER}&h3=${invalidH3}`);
    // Wait for boot. Use mode-resolve as a proxy for "the cell init has run."
    await waitForMode(page, 'cluster');
    await page.waitForTimeout(2000);

    // Drive a hashchange to a different invalid h3, then check that
    // _globeState.selectedH3 was reset (the hashchange null-branch fix).
    await page.evaluate((newH3) => {
      const u = new URL(location.href);
      const params = new URLSearchParams(u.hash.slice(1));
      params.set('h3', newH3);
      // bump heading to force hashchange to fire (same hash wouldn't)
      params.set('heading', '5.0');
      location.hash = '#' + params.toString();
    }, '0baadbeeffffffff');
    await page.waitForTimeout(3000);  // hashchange flight (1.5s) + handler awaits

    const s = await snapshot(page);
    // _globeState.selectedH3 should have been cleared by the null-result
    // branch (no matching cluster found for the malformed h3).
    expect(s.selectedH3).toBeNull();
  });
});
