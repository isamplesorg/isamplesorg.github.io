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
const { explorerUrl } = require('./helpers/url');

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
    await page.goto(explorerUrl());
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

  test('telemetry snapshot survives a facet toggle during held-open COUNT', async ({ page }) => {
    // Codex round-3 review observed that the round-2 race test was still
    // timing-dependent: the wait accepted either "50+" or the final
    // "50 of N" label, so if the COUNT happened to finish before the
    // toggle, the test passed trivially (snapshot or not). To make the
    // test deterministic, we monkey-patch the page's DuckDB `db.query`
    // to add a fixed delay on COUNT(*) queries. That guarantees the
    // toggle lands BETWEEN SELECT completion (visible "50+") and COUNT
    // completion (`finally` log emission), exercising the snapshot's
    // entire purpose.
    //
    // What the snapshot guarantees:
    //   `has_facet_filter` AND `has_source_filter` in the structured
    //   log reflect search-fire-time DOM state, not whatever the user
    //   toggled mid-flight.
    //
    // Fault-injection (verified manually): if the log reads
    // `has_facet_filter` / `has_source_filter` live from DOM in
    // `finally`, this test fails. Both round-1 (predicate snapshot)
    // and round-2 (telemetry snapshot) fixes are exercised.
    const logs = attachSearchLogCollector(page);
    await page.goto(explorerUrl());
    await waitForSearchReady(page);

    // Sanity: no facet active at search-fire time.
    // (Source-filter sanity is NOT checked here because Quarto's
    // see-also rendering duplicates `#sourceFilter` checkboxes in the
    // page DOM, so a naive count is ambiguous. Source-filter snapshot
    // coverage is left as a TODO requiring a non-Quarto fixture.)
    const facetActive = await page.evaluate(() =>
      document.querySelectorAll('#materialFilterBody input[type="checkbox"]:checked').length > 0
      || document.querySelectorAll('#contextFilterBody input[type="checkbox"]:checked').length > 0
      || document.querySelectorAll('#objectTypeFilterBody input[type="checkbox"]:checked').length > 0
    );
    expect(facetActive).toBe(false);

    // Wrap `db.query` to hold COUNT(*) queries open for 1.5s. The page
    // exposes the OJS `db` reactive value via
    // `_ojs.ojsConnector.mainModule.value('db')` — same accessor pattern
    // used by `url-roundtrip.spec.js` for `viewer`. The wrap is scoped
    // to this test's page context so other tests aren't affected.
    await page.evaluate(async () => {
      const db = await window._ojs.ojsConnector.mainModule.value('db');
      if (!db.__countDelayInstalled) {
        const orig = db.query.bind(db);
        db.query = async (sql, ...rest) => {
          if (typeof sql === 'string' && /SELECT\s+COUNT\(\*\)/i.test(sql)) {
            await new Promise(r => setTimeout(r, 1500));
          }
          return orig(sql, ...rest);
        };
        db.__countDelayInstalled = true;
      }
    });

    await runSearch(page, 'pottery');

    // EXACT "50+" wait — proves SELECT has settled AND COUNT has not yet
    // emitted its post-finally log. This is the window the snapshot
    // must survive. Loosening this back to "50+ OR 50 of N" would
    // restore the timing flake Codex round 3 flagged.
    await page.waitForFunction(
      () => document.getElementById('searchResults')?.textContent === '50+ results for "pottery"',
      null, { timeout: 90000 }
    );

    // Toggle the facet checkbox. Programmatic .click() ensures the
    // change event fires through the page's normal handlers.
    await page.evaluate(() => {
      const mat = document.querySelector('#materialFilterBody input[type="checkbox"]');
      if (mat) mat.click();
    });

    // Now wait for the final "50 of N" label. The COUNT was held by
    // the wrap for 1.5s, then runs against the snapshotted SQL, then
    // `finally` logs against the snapshotted booleans.
    await page.waitForFunction(
      () => /^50 of [\d,]+ results for "pottery"$/.test(document.getElementById('searchResults')?.textContent || ''),
      null, { timeout: 90000 }
    );

    const potteryLogs = logs.filter(l => l.term === 'pottery');
    expect(potteryLogs.length).toBeGreaterThan(0);
    const last = potteryLogs[potteryLogs.length - 1];
    // The headline assertion: the snapshotted boolean must be false
    // even though the user ticked a facet between SELECT and COUNT.
    expect(last.has_facet_filter).toBe(false);
    expect(last.results_count).toBe(50);
    expect(last.total_count).not.toBeNull();
    expect(last.total_count).toBeGreaterThan(50);
    expect(last.superseded).toBe(false);
  });

  test('no-results search short-circuits without COUNT (total_count remains null)', async ({ page }) => {
    const logs = attachSearchLogCollector(page);
    await page.goto(explorerUrl());
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
