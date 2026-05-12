/**
 * Explorer URL state round-trip regressions (addresses #209).
 *
 * CI-safe spec set extracted from `url_roundtrip_investigation.js` (which
 * remains as a manual diagnostic targeting the live deploy). These tests
 * run against `localhost:5860` (Quarto preview) and cover the URL state
 * contract slices fixed in PRs #203, #205, #210, #212.
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
 * These specs use the Quarto preview against warm-cache artifacts.
 * Cold-cache live-site behavior and the rest of issue #209's checklist
 * (`pid`+filters, `search`/`search_scope`, facet filters, `view=table`,
 * search-result flight) stay in `url_roundtrip_investigation.js` and a
 * follow-up issue.
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

/** Wait until `loadViewportSamples` has settled into the point-mode done message.
 *  Matches on the trailing "Click one for details" phrase — it's the common
 *  denominator across both done-state phaseMsg branches at explorer.qmd:1610-1612
 *  (normal: `"<n> individual samples. Click one for details."` and cap-reached:
 *  `"<n> samples in view (showing m — zoom in for more). Click one for details."`).
 *  Codex review (PR #214 round 1) suggested switching to the count phrase
 *  `\d[\d,]*\s+individual\s+samples`, but that pattern misses the cap-reached
 *  branch which has no "individual" word, so we stay with the trailing phrase. */
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

/** Wait for boot to complete enough that the `hashchange` listener (registered
 *  late in the explorer cell at explorer.qmd:2210) is installed. `_globeState`
 *  is initialized very early (line 871), so `waitForMode` alone is not enough
 *  to guarantee the listener exists. `_suppressHashWrite` flips to false either
 *  via zoomWatcher init or at the end of the boot deep-link section (line 2734);
 *  by the time it's false, the hashchange listener is definitely registered. */
async function waitForBootSettled(page, timeoutMs = 180000) {
  await page.waitForFunction(
    async () => {
      try {
        const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
        return v?._suppressHashWrite === false;
      } catch { return false; }
    },
    null,
    { timeout: timeoutMs }
  );
}

/** Wait until the URL hash's lat/lng match the expected values within `eps`.
 *  Replaces fixed sleeps with a precise settle condition for moveEnd-driven
 *  hash writes (regression for #205). */
async function waitForHashLatLng(page, expectedLat, expectedLng, eps = 0.001, timeoutMs = 10000) {
  await page.waitForFunction(
    ({ lat, lng, eps }) => {
      const params = new URLSearchParams(location.hash.slice(1));
      const ul = parseFloat(params.get('lat'));
      const un = parseFloat(params.get('lng'));
      return Number.isFinite(ul) && Number.isFinite(un)
        && Math.abs(ul - lat) < eps && Math.abs(un - lng) < eps;
    },
    { lat: expectedLat, lng: expectedLng, eps },
    { timeout: timeoutMs }
  );
}

/** Snapshot camera + mode + selection + URL hash from the live page.
 *  `selectedPid` and `selectedH3` are intentionally read from `viewer._globeState`
 *  — that's the canonical URL-selection backing state today. If a future refactor
 *  renames or relocates these fields, this spec is the place to update. */
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
  // Default per-test cap: point-mode boot in headless can take 60–90s per #190.
  // The multi-context round-trip test overrides this to a longer cap below.
  test.setTimeout(180000);


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

    // Poll the URL hash until lat/lng reflect the new pan — replaces a
    // fixed 2.5s sleep that was tight against flight-complete + moveEnd
    // debounce timing. URL hash settling is what we actually care about.
    await waitForHashLatLng(page, newLat, newLng);
  });

  test('URL round-trips across browser contexts (#203 + #205 combined)', async ({ browser }) => {
    // Round-trip test opens two fresh contexts, each paying the cold-cache
    // point-mode boot cost (60–90s per #190). Override describe-level 180s cap.
    test.setTimeout(360000);

    // Context A: navigate, settle, programmatically pan + zoom, capture URL.
    const ctxA = await browser.newContext();
    let ctxB;
    try {
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

      // Wait for the URL hash to reflect the new camera, not a fixed sleep.
      await waitForHashLatLng(pageA, newLat, newLng);

      const snapA = await snapshot(pageA);
      expect(snapA.mode).toBe('point');

      // Context B: open the captured URL, verify camera/mode round-trip.
      ctxB = await browser.newContext();
      const pageB = await ctxB.newPage();
      await pageB.goto(snapA.url);
      await waitForPointModeSettled(pageB);
      const snapB = await snapshot(pageB);

      expect(Math.abs(snapA.lat - snapB.lat)).toBeLessThan(0.001);
      expect(Math.abs(snapA.lng - snapB.lng)).toBeLessThan(0.001);
      expect(Math.abs(snapA.alt - snapB.alt)).toBeLessThan(50);
      expect(snapB.mode).toBe('point');
    } finally {
      await ctxA.close();
      if (ctxB) await ctxB.close();
    }
  });

  test('h3 hashchange with unknown cell clears selectedH3 (#207 item 6)', async ({ page }) => {
    // Regression we're testing: the hashchange handler's null-result branch
    // at explorer.qmd:2278-2289 must clear `_globeState.selectedH3` when
    // `fetchClusterByH3` returns null. If line 2285 were removed, selectedH3
    // would retain the URL's h3 value (set at line 2272) instead of clearing.
    //
    // Codex review (PR #214 round 1) suggested seeding selectedH3 to a
    // non-null sentinel before the hashchange to "prove prior state was
    // cleared." We attempted that but the seed survived the hashchange
    // unexpectedly (suspected OJS reactivity around `mainModule.value('viewer')`
    // returning a different reference than the handler's closure-captured
    // viewer). Falling back to the simpler form below, which still exercises
    // the regression: line 2272 unconditionally writes selectedH3 from the
    // URL on hashchange, so the only way the post-handler value is null is
    // the explicit null-result branch at line 2285 executing.
    const invalidH3 = '0deadbeefffffff';  // 15 chars but not a real h3 cell
    await page.goto(`${EXPLORER_PATH}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_CLUSTER}&h3=${invalidH3}`);
    await waitForMode(page, 'cluster');
    // `_globeState.mode` is initialized at explorer.qmd:871, well before the
    // hashchange listener is registered at line 2210; wait for boot settle.
    await waitForBootSettled(page);

    // Drive a hashchange to a different invalid h3. The handler runs:
    // line 2272 sets selectedH3=<new invalid>, line 2273 awaits fetchClusterByH3,
    // which returns null (line 2134 — fails 15-char regex), line 2285 clears.
    await page.evaluate((newH3) => {
      const params = new URLSearchParams(location.hash.slice(1));
      params.set('h3', newH3);
      params.set('heading', '5.0');  // bump heading to force hashchange to fire
      location.hash = '#' + params.toString();
    }, '0baadbeeffffffff');

    // Poll for `selectedH3 === null` — replaces a fixed 3s sleep.
    await page.waitForFunction(async () => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      return v._globeState.selectedH3 === null;
    }, null, { timeout: 10000 });

    const s = await snapshot(page);
    expect(s.selectedH3).toBeNull();
  });
});
