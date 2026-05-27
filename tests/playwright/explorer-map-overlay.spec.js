const { test, expect } = require('@playwright/test');
const { explorerUrl } = require('./helpers/url');

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
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
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
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
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
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
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
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
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

  test('table is bbox-scoped: deep-zoom URL yields far fewer rows than world zoom', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });

    // Load at world zoom and read total.
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForBootReady(page);
    await expect(page.locator('#tablePageInfo')).toContainText(/Page 1 of \d+/, { timeout: 60000 });
    const worldText = await page.locator('#tablePageInfo').textContent();
    const worldTotal = parseInt((worldText.match(/of ([\d,]+)\)$/) || [, '0'])[1].replace(/,/g, ''), 10);
    expect(worldTotal).toBeGreaterThan(100000); // world view → millions of samples

    // Fly to Crete-area deep zoom (matches the live-site URL the user reported).
    // Use Promise.race-style: kick off the flight, then wait for the table's
    // pager text to *change* from the world view total. Just polling
    // aria-busy is racy because aria-busy is already false from the boot
    // load, and may briefly stay false between flight start and moveEnd.
    await page.evaluate(async () => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      v.scene.requestRenderMode = false;
      v.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(25.5610, 35.0104, 21299),
        duration: 1.0,
      });
    });

    // Wait for the pager total to change (different total ⇒ refresh against
    // new bbox completed). Use the captured worldText as the not-this guard.
    await expect.poll(
      async () => await page.locator('#tablePageInfo').textContent(),
      { timeout: 60000, intervals: [250, 500, 1000] }
    ).not.toBe(worldText);
    // And aria-busy should land at false after the page+count complete.
    await expect(page.locator('#tableContainer')).toHaveAttribute('aria-busy', 'false', { timeout: 60000 });
    // Belt-and-suspenders: confirm pager actually contains "Page 1 of N (..)"
    // before parsing — without this, a blank/error pager would parseInt to 0
    // and pass the < worldTotal assertion vacuously.
    await expect(page.locator('#tablePageInfo')).toContainText(/Page 1 of \d+ \([\d,]+-[\d,]+ of [\d,]+\)/, { timeout: 30000 });
    const zoomedText = await page.locator('#tablePageInfo').textContent();
    const zoomedTotal = parseInt((zoomedText.match(/of ([\d,]+)\)$/) || [, '0'])[1].replace(/,/g, ''), 10);
    expect(zoomedTotal).toBeGreaterThan(0);

    // The deep-zoom bbox should match far fewer rows than the world view —
    // sanity threshold rather than an exact value (data can change).
    expect(zoomedTotal).toBeLessThan(worldTotal);
    expect(zoomedTotal).toBeLessThan(10000);
  });

  test('table v2: pagination is server-side, pager shows Page X of Y, Next loads new rows', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForBootReady(page);

    // First page should be visible with rows.
    await expect(page.locator('.samples-table tbody tr[data-pid]').first()).toBeVisible({ timeout: 60000 });

    // After COUNT returns, pager text matches "Page 1 of N (1-100 of TOTAL)".
    const pagerLocator = page.locator('#tablePageInfo');
    await expect(pagerLocator).toContainText(/Page 1 of \d+/, { timeout: 60000 });

    // Capture first page's first 3 pids.
    const page1Pids = await page.locator('.samples-table tbody tr[data-pid]')
      .evaluateAll(rows => rows.slice(0, 3).map(r => r.getAttribute('data-pid')));
    expect(page1Pids.length).toBe(3);

    // Click Next; pager should update to Page 2 and rows should differ.
    await page.locator('#tableNext').click();
    await expect(pagerLocator).toContainText(/Page 2 of \d+/, { timeout: 30000 });

    const page2Pids = await page.locator('.samples-table tbody tr[data-pid]')
      .evaluateAll(rows => rows.slice(0, 3).map(r => r.getAttribute('data-pid')));
    expect(page2Pids).not.toEqual(page1Pids);

    // No #maxSamples element exists.
    await expect(page.locator('#maxSamples')).toHaveCount(0);
  });

  test('table v2: filter change clears pager text and re-fetches count', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForBootReady(page);

    await expect(page.locator('#tablePageInfo')).toContainText(/Page 1 of \d+/, { timeout: 60000 });
    const totalAll = await page.locator('#tablePageInfo').textContent();

    // Toggle off one source — total should change.
    await page.locator('#sourceFilter input[value="OPENCONTEXT"]').uncheck();
    // aria-busy goes true during the refetch.
    await expect(page.locator('#tableContainer')).toHaveAttribute('aria-busy', 'true', { timeout: 5000 });
    // Then back to false once both COUNT and page queries return.
    await expect(page.locator('#tableContainer')).toHaveAttribute('aria-busy', 'false', { timeout: 60000 });

    await expect(page.locator('#tablePageInfo')).toContainText(/Page 1 of \d+/, { timeout: 60000 });
    const totalFiltered = await page.locator('#tablePageInfo').textContent();
    expect(totalFiltered).not.toBe(totalAll);
  });

  test('clicking a table row selects the sample, updates #pid hash, and marks the row selected', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(explorerUrl('#v=1&lat=20&lng=0&alt=10000000'), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForBootReady(page);

    // Table loads on boot; wait for at least one data row.
    const firstRow = page.locator('.samples-table tbody tr[data-pid]').first();
    await expect(firstRow).toBeVisible({ timeout: 60000 });
    const pid = await firstRow.getAttribute('data-pid');
    expect(pid, 'first table row should have data-pid').toBeTruthy();

    // Click the row; label cell may be a link — click the source-badge cell
    // (first <td>) to avoid intercepting an <a>.
    await firstRow.locator('td').first().click();

    // .selected class is repainted in place.
    await expect(firstRow).toHaveClass(/\bselected\b/);

    // viewer._globeState.selectedPid is set to this row's pid.
    const selectedPid = await page.evaluate(async () => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      return v && v._globeState ? v._globeState.selectedPid : null;
    });
    expect(selectedPid).toBe(pid);

    // The #pid hash param is written directly by the click handler so it
    // does not depend on zoomWatcher's listener being wired yet.
    const hash = await page.evaluate(() => location.hash);
    expect(hash).toContain(`pid=${encodeURIComponent(pid)}`);
  });

  test('sidebar search input mirrors in-map search input', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(explorerUrl(), {
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
