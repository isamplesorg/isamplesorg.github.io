const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.TEST_URL || 'http://localhost:5860';
const EXPLORER_PATH = '/explorer.html';

// Cesium + OJS boot can be slow on CI; the in-map-overlay specs all wait
// for #cesiumContainer + toolbar render before measuring.
test.describe.configure({ timeout: 90000 });

async function getRect(page, selector) {
  return await page.locator(selector).first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
  });
}

function rectsOverlap(a, b) {
  return !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
}

async function waitForBootReady(page) {
  // Wait for the OJS runtime to attach, then wait for zoomWatcher to resolve
  // (it returns "active" once boot hydration + listener registration are
  // complete — same pattern used in explorer-layout-stability.spec.js).
  await page.waitForFunction(() => !!window._ojs && !!window._ojs.ojsConnector, null, { timeout: 60000 });
  await page.evaluate(async () => {
    return await window._ojs.ojsConnector.mainModule.value('zoomWatcher');
  });
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

  test('iPhone SE (320px): overlay clears toolbar and search buttons do not overflow', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=10000000`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await page.waitForSelector('.cesium-viewer-toolbar', { timeout: 30000 });
    await page.waitForSelector('.map-search-overlay', { timeout: 10000 });

    const overlay = await getRect(page, '.map-search-overlay');
    const toolbar = await getRect(page, '.cesium-viewer-toolbar');
    expect(rectsOverlap(overlay, toolbar)).toBeFalsy();

    // The two scope buttons must not overflow the .search-actions row at
    // narrow widths. The 400px media query stacks them vertically; assert
    // that no button's right edge exceeds its parent's right edge.
    const overflow = await page.evaluate(() => {
      const actions = document.querySelector('.map-search-overlay .search-actions');
      if (!actions) return { error: 'no .search-actions' };
      const aRect = actions.getBoundingClientRect();
      return [...actions.querySelectorAll('button')].map((b) => {
        const r = b.getBoundingClientRect();
        return { text: b.textContent, overflows: r.right > aRect.right + 0.5 || r.left < aRect.left - 0.5 };
      });
    });
    for (const row of overflow) {
      expect(row.overflows, `button "${row.text}" overflows .search-actions at 320px`).toBeFalsy();
    }
  });

  test('base-layer picker dropdown is clickable (not occluded) above the overlay', async ({ page }) => {
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

    // z-index sanity check.
    const zCompare = await page.evaluate(() => {
      const dd = document.querySelector('.cesium-baseLayerPicker-dropDown');
      const ov = document.querySelector('.map-search-overlay');
      const z = (el) => parseInt(getComputedStyle(el).zIndex, 10);
      return { dd: z(dd), ov: z(ov) };
    });
    expect(zCompare.dd, `dropdown z-index (${zCompare.dd}) must beat overlay (${zCompare.ov})`).toBeGreaterThan(zCompare.ov);

    // Real hit-test: at a point inside the dropdown that overlaps the
    // overlay's bounding box, elementFromPoint must return the dropdown
    // (or one of its descendants) — not the overlay.
    const hit = await page.evaluate(() => {
      const dd = document.querySelector('.cesium-baseLayerPicker-dropDown');
      const ov = document.querySelector('.map-search-overlay');
      const ddR = dd.getBoundingClientRect();
      const ovR = ov.getBoundingClientRect();
      // Find an x,y inside the intersection of the two rects, if any.
      const x = Math.max(ddR.left, ovR.left) + 4;
      const y = Math.max(ddR.top, ovR.top) + 4;
      const overlap = !(ddR.right <= ovR.left || ovR.right <= ddR.left || ddR.bottom <= ovR.top || ovR.bottom <= ddR.top);
      if (!overlap) return { overlap: false };
      const hitEl = document.elementFromPoint(x, y);
      return {
        overlap: true,
        x, y,
        hitTag: hitEl && hitEl.tagName,
        hitInDropdown: !!(hitEl && dd.contains(hitEl)),
        hitInOverlay: !!(hitEl && ov.contains(hitEl)),
      };
    });
    // Either there's no geometric overlap (no risk), or the dropdown wins.
    if (hit.overlap) {
      expect(hit.hitInDropdown, `elementFromPoint at (${hit.x},${hit.y}) hit ${hit.hitTag}, expected dropdown descendant. hitInOverlay=${hit.hitInOverlay}`).toBeTruthy();
    }
  });

  test('sidebar search input mirrors in-map search input', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${BASE_URL}${EXPLORER_PATH}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#sampleSearch', { timeout: 30000 });
    await page.waitForSelector('#sampleSearchSidebar', { timeout: 10000 });

    await waitForBootReady(page);

    await page.locator('#sampleSearchSidebar').fill('pottery');
    await expect(page.locator('#sampleSearch')).toHaveValue('pottery');

    await page.locator('#sampleSearch').fill('basalt');
    await expect(page.locator('#sampleSearchSidebar')).toHaveValue('basalt');
  });
});
