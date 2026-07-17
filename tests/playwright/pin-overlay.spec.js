// #172 pin-overlay Inc 1 (option C): after a search completes the located
// results are rendered as a temporary pin overlay on the globe
// (viewer.searchResultPoints), independent of the H3 cluster / sample-point
// layers. These specs assert the overlay's population, cap, replacement, and
// committed-clear lifecycle end-to-end against the published data.
//
// Run:  BASE_URL=https://rdhyee.github.io/isamplesorg.github.io \
//       npx playwright test tests/playwright/pin-overlay.spec.js
//
// Test hook: window.__searchPins() returns viewer.searchResultPoints.length
// (set in the viewer cell). Ground truths reuse the FTS suite's 202608 index
// facts: 'pottery Cyprus' → 1,305 matches; 'basalt' → 785 — both far exceed
// the LIMIT 50 display cap, so the displayed set (and thus the pin set) is
// capped at 50.

const { test, expect } = require('@playwright/test');

const BASE = process.env.BASE_URL || 'https://rdhyee.github.io/isamplesorg.github.io';
const URL = `${BASE}/explorer.html`;

// Generous flake protection matching the FTS suite: a cold CDN edge pays boot
// + lazy module import + sidecar/shard fetches before the first search lands.
test.describe.configure({ retries: process.env.CI ? 1 : 0 });

const pins = (page) => page.evaluate(() => (window.__searchPins ? window.__searchPins() : -1));
const rowPids = (page) =>
  page.$$eval('#samplesSection .sample-row', (els) => els.map((e) => e.dataset.pid));

async function submitSearch(page, term) {
  await page.fill('#sampleSearch', term);
  await page.locator('#searchSubmitBtn').first().click();
}

test.describe('search-result pin overlay (#172 Inc 1)', () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ page }) => {
    await page.goto(URL, { timeout: 90_000 });
    await page.waitForSelector('.samples-table tbody tr[data-pid]', { timeout: 120_000 });
    // Pin overlay starts empty before any search.
    expect(await pins(page)).toBe(0);
  });

  test('local-many: pottery Cyprus pins located results, capped at 50', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    // Pins populate synchronously right after the result rows render.
    await page.waitForFunction(() => (window.__searchPins ? window.__searchPins() : 0) > 0,
      null, { timeout: 120_000 });
    const pinCount = await pins(page);
    const displayed = (await rowPids(page)).length;
    expect(pinCount).toBeGreaterThan(0);
    expect(pinCount).toBeLessThanOrEqual(50);
    // One pin per LOCATED displayed result — coord-less rows are skipped, so
    // pins never exceed the displayed set.
    expect(pinCount).toBeLessThanOrEqual(displayed);
  });

  test('zero: a no-hit query renders no pins', async ({ page }) => {
    await submitSearch(page, 'xyzzyqqqplugh');
    await page.waitForFunction(() =>
      /no results|no samples|couldn't build/i.test(
        (document.getElementById('searchResults')?.textContent || '') +
        (document.getElementById('samplesSection')?.textContent || '')),
      null, { timeout: 120_000 });
    expect(await pins(page)).toBe(0);
  });

  test('new search replaces the pin set', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    await page.waitForFunction(() => (window.__searchPins ? window.__searchPins() : 0) > 0,
      null, { timeout: 120_000 });
    const firstPids = await rowPids(page);
    expect(await pins(page)).toBeGreaterThan(0);

    await submitSearch(page, 'basalt');
    // Wait until the count line reflects the NEW term, then for pins to repopulate.
    await page.waitForFunction(() =>
      /results for "basalt"/i.test(document.getElementById('searchResults')?.textContent || ''),
      null, { timeout: 120_000 });
    await page.waitForFunction(() => (window.__searchPins ? window.__searchPins() : 0) > 0,
      null, { timeout: 120_000 });
    const secondPids = await rowPids(page);
    const secondCount = await pins(page);

    expect(secondCount).toBeGreaterThan(0);
    expect(secondCount).toBeLessThanOrEqual(50);
    // Disjoint corpora → the displayed (and thus pinned) set must change.
    expect(secondPids.join(',')).not.toBe(firstPids.join(','));
  });

  test('committed empty search clears the pins', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    await page.waitForFunction(() => (window.__searchPins ? window.__searchPins() : 0) > 0,
      null, { timeout: 120_000 });
    expect(await pins(page)).toBeGreaterThan(0);

    // Empty submit is a committed clear path — doSearch clears the overlay
    // before the too-short early return.
    await submitSearch(page, '');
    await page.waitForFunction(() => (window.__searchPins ? window.__searchPins() : -1) === 0,
      null, { timeout: 60_000 });
    expect(await pins(page)).toBe(0);
  });
});
