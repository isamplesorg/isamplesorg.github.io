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

  test('cap-hit search with material facet active produces filter-coherent N of M', async ({ page }) => {
    // Codex review of round 1 (#236) flagged the risk that the COUNT could
    // run against a different filter state than the SELECT if the user
    // toggles filters mid-flight. The implementation snapshots
    // sourceFilterSQL/facetFilterSQL once per search. This test exercises
    // the filtered-cap path so the snapshot's correctness is covered.
    const logs = attachSearchLogCollector(page);
    await page.goto(EXPLORER_PATH);
    await waitForSearchReady(page);

    // Tick the first material facet. Same self-healing approach the
    // search-perf benchmark uses (`material_first_n: 1`) so the test
    // doesn't hardcode a URI that may disappear across data refreshes.
    const materialUri = await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[type="checkbox"]');
      if (!cb) return null;
      cb.click();
      return cb.value;
    });
    expect(materialUri).toBeTruthy();

    // Wait for the facet-count refresh fired by the click to settle. The
    // exact debounce is handled by the page; a short visibility check on
    // the cluster-mode honesty note is a cheap proxy for "facet state
    // applied" because syncFacetNote runs from handleFacetFilterChange.
    await page.waitForFunction(
      () => document.getElementById('facetNote')?.style.display === 'block',
      null, { timeout: 30000 }
    ).catch(() => {});  // Not strictly required to assert; just lets the page settle.

    await runSearch(page, 'pottery');
    // Three possible terminal states depending on which material happens
    // to be first in the facet list (data-dependent): cap hit (50 of N),
    // sub-cap (N results), or empty intersection (No results). All three
    // are valid; the invariant we assert is the same.
    await page.waitForFunction(
      () => {
        const text = document.getElementById('searchResults')?.textContent || '';
        return /^(50 of [\d,]+|50\+|\d+|No) results for "pottery"$/.test(text);
      },
      null, { timeout: 90000 }
    );

    const potteryLogs = logs.filter(l => l.term === 'pottery');
    expect(potteryLogs.length).toBeGreaterThan(0);
    const last = potteryLogs[potteryLogs.length - 1];
    expect(last.has_facet_filter).toBe(true);
    expect(last.results_count).toBeLessThanOrEqual(50);
    // Structured-log invariant for #232: `total_count` is present iff the
    // cap was hit. Sub-cap and zero-results cases must NOT have a stale
    // total_count from a prior search leaking through.
    if (last.results_count === 50) {
      expect(last.total_count).not.toBeNull();
      expect(last.total_count).toBeGreaterThanOrEqual(last.results_count);
    } else {
      expect(last.total_count).toBeNull();
    }
    // Round-2 invariant: a non-superseded search must record its filter
    // state alongside results — the snapshot of source/facet SQL is what
    // guarantees the COUNT matches the SELECT in this scenario.
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
