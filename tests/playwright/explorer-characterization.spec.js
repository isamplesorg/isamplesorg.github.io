/**
 * Characterization tests for the iSamples Explorer (PR2, issue #249).
 *
 * These tests (all tagged [data]) pin the behaviors that Codex review of the
 * PR1 smoke gate named as missing characterization coverage. They depend on
 * remote parquet loads from data.isamples.org (202608 dataset) and are
 * intentionally NOT in the CI smoke gate (explorer-e2e.yml stays unchanged).
 * Run manually or via workflow_dispatch with spec_filter=explorer-characterization.
 *
 * Tightened per Codex PR2 review: every assertion pins an OBSERVABLE CONTRACT
 * (the table actually filters; the deep-link propagates to the table; the
 * detail card shows a real material), not just internal state that could
 * false-pass during a refactor.
 *
 * Flakiness mitigations: test.setTimeout(180000); expect.poll (60-90s) for
 * every data-dependent assertion; NEVER fixed waitForTimeout.
 *
 * Behavior map:
 *   (a+) search (known single result) -> __searchFilter active AND table total == 1
 *   (a-) clear search     -> __searchFilter.active === false AND filter removed (total > 1)
 *   (b)  material facet   -> table total strictly decreases (parsed ints), aria-busy settles false
 *   (c)  heatmap          -> see heatmap-overlay.spec.js (comment only, no test)
 *   (d1) ?search= URL     -> __searchFilter restored AND #tableMeta shows the match summary
 *   (d2) &pid= URL        -> selectedPid restored AND #clusterSection shows the sample card
 *   (d3) &pid= URL        -> ALSO opens #inMapCard with exact material (#285 fix), and a
 *                            hashchange away from the pid hides the floating card again
 *   (e)  facet hydration  -> >=3 source counts, material URIs, no stuck .recomputing
 *   (f)  detail card      -> known sample row-click -> #inMapCard visible AND exact material value
 */
const { test, expect } = require('@playwright/test');
const { explorerUrl } = require('./helpers/url');
const {
  waitForBootReady,
  waitForFacetUI,
  waitForFacetCountsStable,
  readFacetCounts,
  waitForSearchReady,
  runSearch,
  getSearchFilter,
  getSelectedPid,
} = require('./helpers/explorer');

const WORLD = '#v=1&lat=20&lng=0&alt=10000000';

// Parse the integer total out of #tablePageInfo: "Page 1 of N (1-100 of TOTAL)".
async function tableTotal(page) {
  const t = await page.locator('#tablePageInfo').textContent();
  const m = t && t.match(/of ([\d,]+)\)\s*$/);
  return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
}
// Poll until #tablePageInfo first shows a numeric total, return it.
async function waitForTableTotal(page, timeout = 90000) {
  await expect.poll(async () => await tableTotal(page), { timeout, intervals: [500, 1000, 2000] })
    .toBeGreaterThan(0);
  return await tableTotal(page);
}

test.describe('Explorer characterization tests [data]', () => {
  test.setTimeout(180000);

  // =========================================================================
  // (a+) search-as-filter: a search must scope the TABLE to its matching set.
  //      We use a deterministic known sample ("Object 5404-8" -> exactly the
  //      one OpenContext record ark:/28722/k2p55x96j) so the proof is exact
  //      and stable. (Table-total SCOPE shifts between viewport/global/filtered
  //      states, so cross-state total comparisons are unreliable -- a known
  //      single-result search is the robust way to prove real filtering.)
  // =========================================================================
  test('(a+) [data] search scopes the table to the matching record', async ({ page }) => {
    await page.goto(explorerUrl(WORLD), { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForBootReady(page);
    await waitForSearchReady(page, 90000);
    await runSearch(page, 'Object 5404-8');

    // Internal state activates...
    await expect.poll(
      async () => { const sf = await getSearchFilter(page); return sf && sf.active && sf.kind === 'text'; },
      { timeout: 90000, intervals: [500, 1000, 2000] }
    ).toBe(true);

    // ...AND the table is scoped to exactly the one matching record...
    await expect.poll(
      async () => await tableTotal(page),
      { timeout: 90000, intervals: [500, 1000, 2000] }
    ).toBe(1);

    // ...which is the expected OpenContext sample.
    await expect(page.locator('.samples-table tbody tr[data-pid="ark:/28722/k2p55x96j"]'))
      .toBeVisible({ timeout: 30000 });
  });

  // =========================================================================
  // (a-) negative: clearing a search removes the filter (active=false AND the
  //      table grows beyond the single matched record).
  // =========================================================================
  test('(a-) [data] clear search resets active=false and removes the filter', async ({ page }) => {
    await page.goto(explorerUrl(WORLD), { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForBootReady(page);
    await waitForSearchReady(page, 90000);

    await runSearch(page, 'Object 5404-8');
    await expect.poll(
      async () => { const sf = await getSearchFilter(page); return sf && sf.active; },
      { timeout: 90000, intervals: [500, 1000, 2000] }
    ).toBe(true);
    await expect.poll(async () => await tableTotal(page), { timeout: 90000, intervals: [500, 1000, 2000] })
      .toBe(1);

    const input = page.locator('#sampleSearch').first();
    await input.click();
    await input.press('ControlOrMeta+a');
    await input.press('Delete');
    await page.locator('#searchSubmitBtn').first().click();

    // Filter gone: active=false AND the table is no longer scoped to the 1 match.
    await expect.poll(
      async () => { const sf = await getSearchFilter(page); return sf ? sf.active : false; },
      { timeout: 60000, intervals: [500, 1000, 2000] }
    ).toBe(false);
    await expect.poll(async () => await tableTotal(page), { timeout: 60000, intervals: [500, 1000, 2000] })
      .toBeGreaterThan(1);
  });

  // =========================================================================
  // (b) facet -> table coherence: material checkbox STRICTLY decreases the
  //     table total (parsed integers, not "text changed").
  // =========================================================================
  test('(b) [data] material facet toggle strictly decreases table total', async ({ page }) => {
    await page.goto(explorerUrl(WORLD), { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForBootReady(page);

    const before = await waitForTableTotal(page, 90000);

    await page.waitForFunction(() => document.querySelectorAll('#materialFilterBody input[type="checkbox"]').length > 0, null, { timeout: 60000 });
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[type="checkbox"]');
      if (cb) { cb.checked = true; document.getElementById('materialFilterBody').dispatchEvent(new Event('change', { bubbles: true })); }
    });

    // Settle on the refetch (final aria-busy=false; the transient =true is not
    // asserted -- a fast cached refresh can complete between polls, per Codex).
    await expect.poll(
      async () => await page.locator('#tableContainer').getAttribute('aria-busy'),
      { timeout: 90000, intervals: [250, 500, 1000] }
    ).toBe('false');

    // Selecting ONE material facet must reduce the total (coherence), not just change text.
    await expect.poll(async () => await tableTotal(page), { timeout: 60000, intervals: [500, 1000, 2000] })
      .toBeLessThan(before);
    expect(await tableTotal(page)).toBeGreaterThan(0);
  });

  // =========================================================================
  // (c) heatmap -- fully covered by heatmap-overlay.spec.js (toggle, mutual
  //     exclusion with markers, URL round-trip, no-cap). Not duplicated here.
  // =========================================================================

  // =========================================================================
  // (d1) deep-link ?search=pottery -> restores state AND propagates to the table
  //      (#tableMeta shows the match summary, not just the internal flag).
  // =========================================================================
  test('(d1) [data] ?search=pottery deep-link restores state AND filters the table', async ({ page }) => {
    await page.goto(explorerUrl('?search=pottery' + WORLD), { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });

    await expect.poll(
      async () => { const sf = await getSearchFilter(page); return sf && sf.active && sf.term === 'pottery'; },
      { timeout: 90000, intervals: [500, 1000, 2000] }
    ).toBe(true);

    // Propagation: the table surface reflects the deep-linked search.
    await expect.poll(
      async () => await page.locator('#tableMeta').textContent(),
      { timeout: 90000, intervals: [500, 1000, 2000] }
    ).toMatch(/\d[\d,]* of [\d,]+ "pottery" match/);
  });

  // =========================================================================
  // (d2) deep-link &pid= -> restores selectedPid AND renders the sample card
  //      into #clusterSection (the sidebar half of the pid path). The in-map
  //      card (#inMapCard) half is asserted separately by (d3) below (#285).
  // =========================================================================
  test('(d2) [data] &pid= deep-link restores selectedPid and renders #clusterSection card', async ({ browser }) => {
    // Phase 1: click a row, capture pid + label + the resulting pid URL.
    const ctx1 = await browser.newContext();
    let capturedUrl = null, capturedPid = null, capturedLabel = null;
    try {
      const page1 = await ctx1.newPage();
      await page1.goto(explorerUrl(WORLD), { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page1.waitForSelector('#cesiumContainer', { timeout: 30000 });
      await waitForBootReady(page1);
      const firstRow = page1.locator('.samples-table tbody tr[data-pid]').first();
      await expect(firstRow).toBeVisible({ timeout: 90000 });
      capturedPid = await firstRow.getAttribute('data-pid');
      capturedLabel = (await firstRow.locator('td').nth(1).textContent() || '').trim();
      expect(capturedPid).toBeTruthy();
      await firstRow.locator('td').first().click();
      await expect.poll(async () => await page1.evaluate(() => location.href), { timeout: 30000, intervals: [250, 500, 1000] }).toContain('pid=');
      capturedUrl = await page1.evaluate(() => location.href);
    } finally { await ctx1.close(); }

    // Phase 2: load the pid URL fresh; assert the boot pid path restored state + card.
    const ctx2 = await browser.newContext();
    try {
      const page2 = await ctx2.newPage();
      await page2.goto(capturedUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page2.waitForSelector('#cesiumContainer', { timeout: 30000 });
      await waitForBootReady(page2);
      // selectedPid restored.
      await expect.poll(async () => await getSelectedPid(page2), { timeout: 90000, intervals: [500, 1000, 2000] }).toBe(capturedPid);
      // updateSampleCard rendered the sample into #clusterSection (the real visible effect).
      await expect.poll(
        async () => await page2.evaluate(() => { const el = document.getElementById('clusterSection'); return el ? el.querySelector('.cluster-card') !== null : false; }),
        { timeout: 120000, intervals: [500, 1000, 2000] }
      ).toBe(true);
      // and the card carries the deep-linked sample's label.
      if (capturedLabel) {
        await expect.poll(
          async () => await page2.locator('#clusterSection').textContent(),
          { timeout: 30000, intervals: [500, 1000] }
        ).toContain(capturedLabel);
      }
    } finally { await ctx2.close(); }
  });

  // =========================================================================
  // (e) facet hydration: source counts, material URIs, no stuck .recomputing
  // =========================================================================
  test('(e) [data] facet hydration: source counts, material URIs, no stuck .recomputing', async ({ page }) => {
    await page.goto(explorerUrl('#v=1&lat=0&lng=0&alt=15000000'), { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForFacetUI(page, 90000);
    await waitForFacetCountsStable(page, 90000);

    const sourceCounts = await readFacetCounts(page, 'source');
    expect(Object.values(sourceCounts).filter(n => n > 0).length).toBeGreaterThanOrEqual(3);

    const materialValues = await page.evaluate(() => [...document.querySelectorAll('#materialFilterBody input[type="checkbox"]')].map(cb => cb.value));
    expect(materialValues.length).toBeGreaterThan(0);
    for (const val of materialValues) { expect(val).toMatch(/^https?:\/\//); }

    const stuck = await page.evaluate(() => document.querySelectorAll('.facet-count.recomputing').length);
    expect(stuck).toBe(0);
  });

  // =========================================================================
  // (f) detail card: a KNOWN sample (#260, ark:/28722/k2p55x96j) must show the
  //     in-map card with its EXACT material -- not merely "non-empty", which
  //     would false-pass on "Not Provided" from a failed detail query (Codex).
  // =========================================================================
  test('(f) [data] known sample row-click shows #inMapCard with exact material', async ({ page }) => {
    await page.goto(explorerUrl('?search=Object+5404-8' + WORLD), { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
    await waitForSearchReady(page, 90000);

    // The deep-link search resolves to exactly this OpenContext sample.
    const row = page.locator('.samples-table tbody tr[data-pid="ark:/28722/k2p55x96j"]');
    await expect(row).toBeVisible({ timeout: 120000 });

    expect(await page.locator('#inMapCard').getAttribute('hidden')).not.toBeNull(); // starts hidden
    await row.locator('td').first().click();

    await expect.poll(
      async () => await page.locator('#inMapCard').getAttribute('hidden'),
      { timeout: 60000, intervals: [250, 500, 1000] }
    ).toBeNull();

    // Exact, known material (the #260 fix value) -- pins a real successful detail query.
    await expect.poll(
      async () => (await page.locator('#imcMaterial').textContent() || '').trim(),
      { timeout: 90000, intervals: [500, 1000, 2000] }
    ).toBe('Other anthropogenic material');
  });

  // =========================================================================
  // (d3) #285: a pid deep-link must open the #inMapCard too, not only the
  //      sidebar #clusterSection -- same end state as a row-click (f). Phase 1
  //      row-clicks a KNOWN sample to capture a real pid URL; phase 2 loads it
  //      fresh and asserts the boot pid path opens the in-map card with the
  //      same exact material (f) pins for the row-click path. Fails on the
  //      pre-#285 code, where the deep-link populated only the sidebar.
  // =========================================================================
  test('(d3) [data] &pid= deep-link opens #inMapCard with exact material (#285)', async ({ browser }) => {
    const KNOWN_PID = 'ark:/28722/k2p55x96j';
    const ctx1 = await browser.newContext();
    let capturedUrl = null;
    try {
      const page1 = await ctx1.newPage();
      await page1.goto(explorerUrl('?search=Object+5404-8' + WORLD), { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page1.waitForSelector('#cesiumContainer', { timeout: 30000 });
      await waitForSearchReady(page1, 90000);
      const row = page1.locator(`.samples-table tbody tr[data-pid="${KNOWN_PID}"]`);
      await expect(row).toBeVisible({ timeout: 120000 });
      await row.locator('td').first().click();
      await expect.poll(async () => await page1.evaluate(() => location.href), { timeout: 30000, intervals: [250, 500, 1000] }).toContain('pid=');
      capturedUrl = await page1.evaluate(() => location.href);
    } finally { await ctx1.close(); }

    const ctx2 = await browser.newContext();
    try {
      const page2 = await ctx2.newPage();
      await page2.goto(capturedUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page2.waitForSelector('#cesiumContainer', { timeout: 30000 });
      await waitForBootReady(page2);
      // Boot pid path restored the selection...
      await expect.poll(async () => await getSelectedPid(page2), { timeout: 90000, intervals: [500, 1000, 2000] }).toBe(KNOWN_PID);
      // ...and (the #285 fix) opened the floating in-map card, not just the sidebar.
      await expect.poll(
        async () => await page2.locator('#inMapCard').getAttribute('hidden'),
        { timeout: 120000, intervals: [500, 1000, 2000] }
      ).toBeNull();
      // The shared detail query populated the known material (parity with (f)).
      await expect.poll(
        async () => (await page2.locator('#imcMaterial').textContent() || '').trim(),
        { timeout: 90000, intervals: [500, 1000, 2000] }
      ).toBe('Other anthropogenic material');

      // #285 finding 3: a hashchange away from the pid (to a bare view with no
      // pid/h3) must HIDE the floating card again — otherwise it strands over
      // the map. Drive a same-document hashchange and assert it re-hides.
      await page2.evaluate(() => { location.hash = '#v=1&lat=20&lng=0&alt=10000000'; });
      await expect.poll(
        async () => await page2.locator('#inMapCard').getAttribute('hidden'),
        { timeout: 30000, intervals: [250, 500, 1000] }
      ).not.toBeNull();
    } finally { await ctx2.close(); }
  });
});
