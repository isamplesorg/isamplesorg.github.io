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
      height: r.height,
    };
  });
}

function expectRectStable(actual, expected, tolerance = 2) {
  expect(Math.abs(actual.top - expected.top)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(actual.height - expected.height)).toBeLessThanOrEqual(tolerance);
}

test.describe('explorer layout stability', () => {
  test('desktop globe rect is stable across boot, status, point mode, and table round trip', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });

    const initialRect = await elementRect(page, '#cesiumContainer');
    expect(Math.abs(initialRect.height - 585)).toBeLessThanOrEqual(2);

    await waitForClusterBoot(page);
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    await page.locator('#searchResults').evaluate((el) => {
      el.textContent = '50+ results for a deliberately long search status that wraps across two reserved lines';
    });
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    await flyCameraTo(page, LAT_CYPRUS, LNG_CYPRUS, ALT_POINT_CYPRUS);
    await waitForMode(page, 'point');
    await waitForPhaseMessage(page, 'individual samples', 120000);
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    await page.locator('#tableViewBtn').click();
    await expect(page.locator('.globe-layout')).toBeHidden();
    await expect(page.locator('#tableContainer')).toBeVisible();
    const tableRect = await elementRect(page, '#tableContainer');
    expect(Math.abs(tableRect.top - initialRect.top)).toBeLessThanOrEqual(2);

    await page.locator('#globeViewBtn').click();
    await expect(page.locator('.globe-layout')).toBeVisible();
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);
  });

  test('mobile globe height override is stable across boot and wrapped status', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });

    const initialRect = await elementRect(page, '#cesiumContainer');
    expect(Math.abs(initialRect.height - 489.52)).toBeLessThanOrEqual(2);

    await waitForClusterBoot(page);
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);

    await page.locator('#searchResults').evaluate((el) => {
      el.textContent = 'Search error: a long mobile status message that should scroll inside its reserved slot';
    });
    expectRectStable(await elementRect(page, '#cesiumContainer'), initialRect);
  });
});
