/**
 * Search-results "50+" → "50 of N" real-count display (issue #232,
 * roadmap step 2 of #234).
 *
 * Regression-prone area: the search-results line under the in-map search
 * box used to read `50+ results for "pottery"` whenever the SELECT hit
 * `LIMIT 50`, hiding whether the true result set is 51 or 50,000. The
 * fix follows the same pattern as `loadViewportSamples()`'s real-count
 * follow-up: when the cap is hit, fire a second `COUNT(*)` query with
 * the same WHERE clause and replace the label.
 *
 * What this spec covers:
 *   - Cap-hit case ("pottery"): initial `50+` followed by the
 *     `50 of N` final label where N > 50, AND the structured
 *     `isamples.search` log payload reports `total_count: N`.
 *   - No-results case ("xyzzyqqqplugh"): `No results for "term"` still
 *     short-circuits without firing the COUNT scan; structured log
 *     reports `total_count: null`.
 *
 * What this spec does NOT cover:
 *   - Cancellation race when a second search supersedes the COUNT
 *     in flight. Covered conceptually by the `searchId !== _searchSeq`
 *     guard in the implementation; a Playwright test that reliably
 *     races two SELECTs against each other would be fragile.
 *   - Sub-cap results (e.g., 12 results) — the rendering path is
 *     unchanged from pre-#232 ("N results for term" with no "of M").
 */
const { test, expect } = require('@playwright/test');

const EXPLORER_PATH = '/explorer.html';

/** Wait until the explorer has rendered the search input. Boot sequence:
 *  phase1 (viewer + cluster cache) → facetFilters → search input wiring.
 *  The input is in the DOM from page load but only functional after wiring. */
async function waitForSearchReady(page, ms = 60000) {
  await page.locator('#sampleSearch').first().waitFor({ timeout: ms });
  await page.locator('#searchSubmitBtn').first().waitFor({ timeout: ms });
  // The search results line is created at boot too — wait for the
  // facetFilters cell to settle so a search fires against a populated
  // facet UI (matches what a real user would experience).
  await page.waitForFunction(
    () => document.querySelectorAll('#materialFilterBody input[type="checkbox"]').length > 0,
    null, { timeout: ms }
  );
}

/** Collect `isamples.search` JSON payloads from the console (matches the
 *  pattern used in tests/test_search_perf.py:204). */
function attachSearchLogCollector(page) {
  const captured = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'log') return;
    const text = msg.text();
    if (!text.includes('isamples.search')) return;
    try {
      const payload = JSON.parse(text);
      if (payload?.event === 'isamples.search') captured.push(payload);
    } catch { /* not a structured search log */ }
  });
  return captured;
}

async function runSearch(page, term) {
  // Quarto's see-also rendering produces a duplicate #sampleSearch in the
  // DOM; `document.getElementById` (which the live JS uses) resolves to
  // the FIRST instance, so the test mirrors that with `.first()`.
  const input = page.locator('#sampleSearch').first();
  await input.click();
  await input.press('ControlOrMeta+a');
  await input.press('Delete');
  await input.fill(term);
  await page.locator('#searchSubmitBtn').first().click();
}

test.describe('Search real-count display (#232 / #234 step 2)', () => {
  test.setTimeout(180000);

  test('cap-hit search shows "N of M results" + structured log carries total_count', async ({ page }) => {
    const logs = attachSearchLogCollector(page);
    await page.goto(EXPLORER_PATH);
    await waitForSearchReady(page);

    await runSearch(page, 'pottery');

    // First wait for the "50+" initial state — proves the cap-hit
    // initial render is in place before the COUNT lands.
    await page.waitForFunction(
      () => /^50\+ results for "pottery"$/.test(document.getElementById('searchResults')?.textContent || ''),
      null, { timeout: 90000 }
    );

    // Then wait for the COUNT to land and the label to flip to "50 of N".
    // The thousands separator is from `Number.toLocaleString()`, which uses
    // the test browser's locale (en-US in playwright defaults), so we
    // tolerate either comma-separated or plain digits to be portable.
    await page.waitForFunction(
      () => {
        const text = document.getElementById('searchResults')?.textContent || '';
        return /^50 of [\d,]+ results for "pottery"$/.test(text);
      },
      null, { timeout: 60000 }
    );

    // Pull the structured log payload back and verify total_count > 50.
    // Wait until the COUNT-bearing log appears (the log is written from
    // `finally`, which runs after COUNT).
    await page.waitForFunction(
      () => true,  // give the console event a tick to land
      null, { timeout: 1000 }
    ).catch(() => {});

    const potteryLogs = logs.filter(l => l.term === 'pottery');
    expect(potteryLogs.length).toBeGreaterThan(0);
    const last = potteryLogs[potteryLogs.length - 1];
    expect(last.results_count).toBe(50);
    expect(last.total_count).toBeGreaterThan(50);
    expect(typeof last.count_ms).toBe('number');
    expect(last.count_ms).toBeGreaterThan(0);
    expect(last.superseded).toBe(false);

    // And the visible label matches the log payload. `.first()` for the
    // same reason as #sampleSearch above — Quarto duplicates the node.
    const visible = await page.locator('#searchResults').first().textContent();
    const m = visible.match(/^50 of ([\d,]+) results for "pottery"$/);
    expect(m).toBeTruthy();
    const visibleTotal = Number(m[1].replace(/,/g, ''));
    expect(visibleTotal).toBe(last.total_count);
  });

  test('telemetry snapshot survives a facet toggle during search await', async ({ page }) => {
    // Codex round-2 review observed that the round-1 filtered test
    // wouldn't actually have caught a missing snapshot — it ticked a
    // facet BEFORE searching, so SELECT and COUNT saw the same DOM state
    // regardless of whether the snapshot existed. This stronger test
    // exercises the race directly: fire the search with no facets,
    // wait until the SELECT visibly completes (the "50+ results" label),
    // then tick a material facet, then wait for the structured log.
    //
    // What the snapshot guarantees:
    //   `has_facet_filter` in the log reflects search-fire-time state
    //   (false), not the post-toggle DOM state (true).
    //
    // If the snapshot is removed (DOM-live reads in `finally`), this
    // assertion will fail.
    const logs = attachSearchLogCollector(page);
    await page.goto(EXPLORER_PATH);
    await waitForSearchReady(page);

    // Sanity: no facet active at search-fire time.
    const facetActiveBefore = await page.evaluate(() => {
      return document.querySelectorAll('#materialFilterBody input[type="checkbox"]:checked').length > 0
          || document.querySelectorAll('#contextFilterBody input[type="checkbox"]:checked').length > 0
          || document.querySelectorAll('#objectTypeFilterBody input[type="checkbox"]:checked').length > 0;
    });
    expect(facetActiveBefore).toBe(false);

    await runSearch(page, 'pottery');

    // Wait for the SELECT to visibly settle (initial "50+" label or the
    // final "50 of N" — either proves SELECT done, and toggling now
    // simulates a user mid-flight facet change).
    await page.waitForFunction(
      () => /^(50\+|50 of [\d,]+) results for "pottery"$/.test(document.getElementById('searchResults')?.textContent || ''),
      null, { timeout: 90000 }
    );

    // Tick a material facet — this is the toggle the snapshot must
    // survive. Programmatic .click() is used so the change event fires
    // and the page's normal handlers run (mirrors user interaction).
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[type="checkbox"]');
      if (cb) cb.click();
    });

    // Wait for the search to fully settle: either the final "50 of N"
    // label appeared (COUNT completed before or after the toggle), or
    // the structured log row landed for this search id.
    await page.waitForFunction(
      () => /^50 of [\d,]+ results for "pottery"$/.test(document.getElementById('searchResults')?.textContent || ''),
      null, { timeout: 90000 }
    );

    // Pull the log payload for this search (filter by term). With the
    // snapshot, `has_facet_filter` must be false (state at search-fire
    // time). Without the snapshot, the DOM-live read in `finally` would
    // see the post-toggle checkbox and report true.
    const potteryLogs = logs.filter(l => l.term === 'pottery');
    expect(potteryLogs.length).toBeGreaterThan(0);
    const last = potteryLogs[potteryLogs.length - 1];
    expect(last.has_facet_filter).toBe(false);
    expect(last.results_count).toBe(50);
    expect(last.total_count).not.toBeNull();
    expect(last.total_count).toBeGreaterThan(50);
    // Search itself was not superseded — only a facet toggle happened,
    // not a fresh search submission.
    expect(last.superseded).toBe(false);
  });

  test('no-results search short-circuits without COUNT (total_count remains null)', async ({ page }) => {
    const logs = attachSearchLogCollector(page);
    await page.goto(EXPLORER_PATH);
    await waitForSearchReady(page);

    await runSearch(page, 'xyzzyqqqplugh');

    await page.waitForFunction(
      () => /^No results for "xyzzyqqqplugh"$/.test(document.getElementById('searchResults')?.textContent || ''),
      null, { timeout: 90000 }
    );

    const xyzzyLogs = logs.filter(l => l.term === 'xyzzyqqqplugh');
    expect(xyzzyLogs.length).toBeGreaterThan(0);
    const last = xyzzyLogs[xyzzyLogs.length - 1];
    expect(last.results_count).toBe(0);
    expect(last.total_count).toBeNull();
    // COUNT path not entered ⇒ countMs stayed at 0.
    expect(last.count_ms).toBe(0);
  });
});
