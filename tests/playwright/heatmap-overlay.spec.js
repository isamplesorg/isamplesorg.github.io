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

  test('heatmap toggle exists', async ({ page }) => {
    await openExplorer(page);
    await expect(page.locator('#heatmapToggle')).toBeVisible();
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
  });
});
