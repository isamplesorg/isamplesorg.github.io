const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.TEST_URL || 'http://localhost:5860';
const EXPLORER_PATH = '/explorer.html';

const ALT_WORLD = 10000000;
const ALT_POINT_CYPRUS = 62054;
const LAT_CYPRUS = 34.9954;
const LNG_CYPRUS = 33.7052;

async function waitForPhaseMessage(page, substring, timeoutMs = 60000) {
  return await page.waitForFunction(
    (sub) => {
      const el = document.getElementById('phaseMsg');
      const text = el ? el.textContent : '';
      return text.includes(sub) ? text.trim() : null;
    },
    substring,
    { timeout: timeoutMs }
  ).then(handle => handle.jsonValue());
}

async function waitForClusterBoot(page) {
  await waitForPhaseMessage(page, 'clusters,');
  // Awaiting `value('zoomWatcher')` ensures the OJS cell has finished
  // running — listener registration + boot hydration are complete by the
  // time this resolves. The cell returns the string "active" so we don't
  // use the return value, only the await.
  await page.evaluate(async () => {
    return await window._ojs.ojsConnector.mainModule.value('zoomWatcher');
  });
}

async function waitForMode(page, expected, timeoutMs = 120000) {
  await page.waitForFunction(
    async (expectedMode) => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      return v && v._globeState && v._globeState.mode === expectedMode;
    },
    expected,
    { timeout: timeoutMs }
  );
}

async function flyCameraTo(page, lat, lng, alt) {
  await page.evaluate(async ({ lat, lng, alt }) => {
    const v = await window._ojs.ojsConnector.mainModule.value('viewer');
    v.scene.requestRenderMode = false;
    v.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lng, lat, alt),
      duration: 1.0,
    });
  }, { lat, lng, alt });
}

async function settleLayout(page) {
  await page.evaluate(() => new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
}

async function elementRect(page, selector) {
  await settleLayout(page);
  return await page.locator(selector).evaluate((el) => {
    const r = el.getBoundingClientRect();
    return {
      top: r.top,
      width: r.width,
      height: r.height,
    };
  });
}

function expectRectStable(actual, expected, tolerance = 2) {
  expect(Math.abs(actual.top - expected.top)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(actual.width - expected.width)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(actual.height - expected.height)).toBeLessThanOrEqual(tolerance);
}

/** Resolve `var(--explorer-map-height)` to a computed px value via a hidden
 *  probe element. Reading the custom property directly via
 *  `getPropertyValue('--explorer-map-height')` returns the unresolved
 *  `clamp(...)` string, not a px value. */
async function resolveMapHeightPx(page) {
  return await page.evaluate(() => {
    const probe = document.createElement('div');
    probe.style.cssText = 'height: var(--explorer-map-height); position: absolute; visibility: hidden;';
    document.body.appendChild(probe);
    const h = probe.getBoundingClientRect().height;
    probe.remove();
    return h;
  });
}

test.describe('explorer layout stability', () => {
  test('desktop globe rect is stable across boot, status, and point-mode flight; table is permanent below', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });

    const initialRect = await elementRect(page, '#cesiumContainer');
    expect(initialRect.width).toBeGreaterThanOrEqual(840);
    // Per M-5 the map height was reduced from clamp(500,65vh,680) to
    // clamp(400,50vh,540). At 1280x900 desktop, 50vh = 450 (within the
    // clamp range). Derive from the probe rather than hardcoding.
    const expectedDesktopMapHeight = await resolveMapHeightPx(page);
    expect(expectedDesktopMapHeight).toBeGreaterThanOrEqual(400);
    expect(expectedDesktopMapHeight).toBeLessThanOrEqual(540);
    expect(Math.abs(initialRect.height - expectedDesktopMapHeight)).toBeLessThanOrEqual(2);

    await waitForClusterBoot(page);
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    await page.locator('#searchResults').evaluate((el) => {
      el.textContent = '50+ results for a deliberately long search status that wraps across two reserved lines';
    });
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    await flyCameraTo(page, LAT_CYPRUS, LNG_CYPRUS, ALT_POINT_CYPRUS);
    await waitForMode(page, 'point');
    // Wait on the trailing phrase common to BOTH point-mode done branches
    // (normal: "<N> individual samples. Click one for details." and cap-reached:
    // "<N> samples in view (showing M — zoom in for more). Click one for details.")
    // rather than "individual samples", which misses the cap-reached path.
    await waitForPhaseMessage(page, 'Click one for details', 120000);
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    // Table is now permanent (M-5). Both .globe-layout and #tableContainer
    // are visible at the same time; table sits below the globe.
    await expect(page.locator('.globe-layout')).toBeVisible();
    await expect(page.locator('#tableContainer')).toBeVisible();
    const tableRect = await elementRect(page, '#tableContainer');
    expect(tableRect.top).toBeGreaterThan(initialRect.top + initialRect.height - 4);
    // No view-toggle buttons should exist anymore.
    await expect(page.locator('#globeViewBtn')).toHaveCount(0);
    await expect(page.locator('#tableViewBtn')).toHaveCount(0);
  });

  test('mobile globe height override is stable across boot and wrapped status', async ({ page }) => {
    const viewport = { width: 390, height: 844 };
    await page.setViewportSize(viewport);
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });

    const initialRect = await elementRect(page, '#cesiumContainer');
    // Per M-5, mobile CSS resolves `clamp(360px, 50vh, 480px)` (was
    // 360/58/520 pre-M-5). At 390×844, 50vh = 422. Derive expected via
    // the probe helper.
    const expectedMapHeight = await resolveMapHeightPx(page);
    // Sanity: must be within the new mobile clamp bounds [360, 480].
    expect(expectedMapHeight).toBeGreaterThanOrEqual(360);
    expect(expectedMapHeight).toBeLessThanOrEqual(480);
    expect(Math.abs(initialRect.height - expectedMapHeight)).toBeLessThanOrEqual(2);

    await waitForClusterBoot(page);
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    await page.locator('#searchResults').evaluate((el) => {
      el.textContent = 'Search error: a long mobile status message that should scroll inside its reserved slot';
    });
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);
  });

  test('small-phone (320×568) clamps map height to the 360px floor', async ({ page }) => {
    // At 320×568, mobile CSS resolves `clamp(360px, 50vh, 480px)` with
    // 50vh = 284px — below the 360px floor — so map height = 360px.
    // Covers the clamp-floor branch which the 390×844 case never exercises.
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });

    const initialRect = await elementRect(page, '#cesiumContainer');
    const expectedMapHeight = await resolveMapHeightPx(page);
    expect(expectedMapHeight).toBe(360);
    expect(Math.abs(initialRect.height - 360)).toBeLessThanOrEqual(2);

    await waitForClusterBoot(page);
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);
  });
});
