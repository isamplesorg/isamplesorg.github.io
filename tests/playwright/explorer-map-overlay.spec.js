const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.TEST_URL || 'http://localhost:5860';
const EXPLORER_PATH = '/explorer.html';

async function getRect(page, selector) {
  return await page.locator(selector).first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
  });
}

function rectsOverlap(a, b) {
  return !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
}

test.describe('Map search overlay — Cesium toolbar coexistence (#200 / M-1A)', () => {
  test('desktop: overlay does not cover Cesium toolbar buttons', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=10000000`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await page.waitForSelector('.cesium-viewer-toolbar', { timeout: 30000 });
    await page.waitForSelector('.map-search-overlay', { timeout: 10000 });

    const overlay = await getRect(page, '.map-search-overlay');
    const toolbar = await getRect(page, '.cesium-viewer-toolbar');
    expect(rectsOverlap(overlay, toolbar), `overlay ${JSON.stringify(overlay)} overlaps toolbar ${JSON.stringify(toolbar)}`).toBeFalsy();

    // Each individual toolbar child button should also be unobstructed.
    const buttonCount = await page.locator('.cesium-viewer-toolbar > *').count();
    expect(buttonCount).toBeGreaterThan(0);
    for (let i = 0; i < buttonCount; i++) {
      const btn = await page.locator('.cesium-viewer-toolbar > *').nth(i).evaluate((el) => {
        const r = el.getBoundingClientRect();
        return { top: r.top, left: r.left, right: r.right, bottom: r.bottom };
      });
      expect(rectsOverlap(overlay, btn), `overlay obstructs toolbar button #${i} (${JSON.stringify(btn)})`).toBeFalsy();
    }
  });

  test('mobile (390px): overlay does not cover Cesium toolbar', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=10000000`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await page.waitForSelector('.cesium-viewer-toolbar', { timeout: 30000 });
    await page.waitForSelector('.map-search-overlay', { timeout: 10000 });

    const overlay = await getRect(page, '.map-search-overlay');
    const toolbar = await getRect(page, '.cesium-viewer-toolbar');
    expect(rectsOverlap(overlay, toolbar), `mobile overlay ${JSON.stringify(overlay)} overlaps toolbar ${JSON.stringify(toolbar)}`).toBeFalsy();
  });

  test('base-layer picker dropdown opens above the search overlay', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=10000000`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('.cesium-baseLayerPicker-selected', { timeout: 30000 });
    await page.waitForSelector('.map-search-overlay', { timeout: 10000 });

    await page.locator('.cesium-baseLayerPicker-selected').click();
    const dropdown = page.locator('.cesium-baseLayerPicker-dropDown').first();
    await expect(dropdown).toBeVisible({ timeout: 5000 });

    // The dropdown geometrically overlaps the overlay area; what matters is
    // that the dropdown wins the z-stack so its options are clickable.
    // Resolve effective z-index of both via getComputedStyle.
    const zCompare = await page.evaluate(() => {
      const dd = document.querySelector('.cesium-baseLayerPicker-dropDown');
      const ov = document.querySelector('.map-search-overlay');
      const z = (el) => parseInt(getComputedStyle(el).zIndex, 10);
      return { dd: z(dd), ov: z(ov) };
    });
    expect(zCompare.dd, `base-layer-picker dropdown z-index (${zCompare.dd}) must beat overlay (${zCompare.ov})`).toBeGreaterThan(zCompare.ov);
  });

  test('sidebar search input mirrors in-map search input', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#sampleSearch', { timeout: 30000 });
    await page.waitForSelector('#sampleSearchSidebar', { timeout: 10000 });

    // The mirror is wired in the zoomWatcher OJS cell — wait for it to be ready.
    await page.evaluate(async () => {
      return await window._ojs.ojsConnector.mainModule.value('zoomWatcher');
    });

    await page.locator('#sampleSearchSidebar').fill('pottery');
    await expect(page.locator('#sampleSearch')).toHaveValue('pottery');

    await page.locator('#sampleSearch').fill('basalt');
    await expect(page.locator('#sampleSearchSidebar')).toHaveValue('basalt');
  });
});
