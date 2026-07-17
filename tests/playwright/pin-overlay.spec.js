// #172 pin-overlay Inc 1 (option C): after a search completes the located
// results are rendered as a temporary pin overlay on the globe
// (viewer.searchResultPoints), independent of the H3 cluster / sample-point
// layers. These specs assert population, exact set equality with the located
// displayed rows, the 50 cap, pin-set replacement, and the snapshot-semantics
// clear lifecycle end-to-end against the published data.
//
// Run (branch dispatch honors the config's TEST_URL; BASE_URL is a manual
// fallback, production the last resort — a dispatch that sets TEST_URL tests
// the worktree, not production, per Codex round-1 P1.4f):
//   TEST_URL=https://<branch-pages-url> npx playwright test tests/playwright/pin-overlay.spec.js
//
// Test hooks (both set in the viewer cell):
//   window.__searchPins()      → [{ pid, lat, lng }] read-only snapshot.
//   window.__clickSearchPin(i) → replays the on-globe result-pin click ceremony
//                                (shared helper + pid hash push) by index, since
//                                Cesium canvas picking isn't feasible in Playwright.
// Ground truths reuse the FTS suite's 202608 index facts: 'pottery Cyprus' →
// 1,305 matches; 'basalt' → 785 — both exceed the LIMIT 50 display cap, so the
// displayed (and pinned) set is capped at 50. 'ark:/28722/k2000hz7r' is the FTS
// suite's known-present single pid.
//
// ASYNC INTERLEAVING (Codex round-3): the "a hydration must not overwrite a
// newer search's list/pins" invariant is guaranteed by the freshness-token
// OWNERSHIP audit, not by a timing-dependent e2e test. doSearch()/doDescribedBy()
// bump the selection token at entry (new panel owner), and every post-await
// list-mutation site (direct cluster-click nearby path, hydrateClusterUI) checks
// isStale() and re-clears pins as one owned operation before writing the list. A
// true interleaving race test would be flaky (it depends on two concurrent DuckDB
// queries resolving in a specific order), so per the review guidance we do not
// ship one; the Back-after-pin-click test below exercises the deterministic
// half of the lifecycle.

const { test, expect } = require('@playwright/test');

const BASE = process.env.TEST_URL || process.env.BASE_URL
  || 'https://rdhyee.github.io/isamplesorg.github.io';
const URL = `${BASE}/explorer.html`;

// Generous flake protection matching the FTS suite: a cold CDN edge pays boot
// + lazy module import + sidecar/shard fetches before the first search lands.
test.describe.configure({ retries: process.env.CI ? 1 : 0 });

// [{ pid, lat, lng }] snapshot of the live overlay.
const pins = (page) => page.evaluate(() => (window.__searchPins ? window.__searchPins() : []));

// PIDs of the LOCATED search-result rows in the side panel. Rows carry
// data-lat="null"/"" when the match has no coordinates (world-scope LEFT JOIN);
// those are exactly the rows the overlay skips.
const locatedRowPids = (page) =>
  page.$$eval('#samplesSection .sample-row', (els) =>
    els
      .filter((e) => {
        const la = e.dataset.lat, ln = e.dataset.lng;
        return la && la !== 'null' && la !== 'undefined'
            && ln && ln !== 'null' && ln !== 'undefined';
      })
      .map((e) => e.dataset.pid));

const displayedRowCount = (page) =>
  page.$$eval('#samplesSection .sample-row', (els) => els.length);

const searchState = (page) => page.evaluate(() => {
  const sf = window.__searchFilter || {};
  return {
    active: sf.active,
    total: sf.total,
    term: sf.term,
    substrate: sf.substrate,
    resultsText: document.getElementById('searchResults')?.textContent || '',
    panelText: document.getElementById('samplesSection')?.textContent || '',
  };
});

const sortJoin = (arr) => [...arr].sort().join('|');

async function submitSearch(page, term) {
  await page.fill('#sampleSearch', term);
  await page.locator('#searchSubmitBtn').first().click();
}

// Wait until the results line settles on a terminal state (not the transient
// "Searching…"/"Building…" messages).
async function waitSearchSettled(page) {
  await page.waitForFunction(() => {
    const s = (document.getElementById('searchResults')?.textContent || '').trim();
    return s.length > 0 && !/^(searching|building)/i.test(s);
  }, null, { timeout: 120_000 });
}

async function waitPinsAtLeast(page, n) {
  await page.waitForFunction(
    (min) => (window.__searchPins ? window.__searchPins().length : 0) >= min,
    n, { timeout: 120_000 });
}

test.describe('search-result pin overlay (#172 Inc 1)', () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ page }) => {
    await page.goto(URL, { timeout: 90_000 });
    await page.waitForSelector('.samples-table tbody tr[data-pid]', { timeout: 120_000 });
    // Pin overlay starts empty before any search.
    expect((await pins(page)).length).toBe(0);
  });

  test('local-many: pins are EXACTLY the located displayed rows, capped at 50', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    await waitPinsAtLeast(page, 1);
    await waitSearchSettled(page);

    const pinList = await pins(page);
    const pinPids = pinList.map((p) => p.pid);
    const located = await locatedRowPids(page);
    const displayed = await displayedRowCount(page);

    // Cap: at most the LIMIT 50 display set, and never more than displayed.
    expect(pinPids.length).toBeGreaterThan(0);
    expect(pinPids.length).toBeLessThanOrEqual(50);
    expect(pinPids.length).toBeLessThanOrEqual(displayed);
    // Documented total (1,305) exceeds the LIMIT 50 cap, so it must bind exactly.
    expect(displayed).toBe(50);
    // Exact set equality: one pin per located displayed row, no more, no fewer.
    expect(sortJoin(pinPids)).toBe(sortJoin(located));
    // Every pin carries real coordinates (never coerced to 0,0 placeholders).
    for (const p of pinList) {
      expect(typeof p.lat).toBe('number');
      expect(typeof p.lng).toBe('number');
    }
  });

  test('one: a single-pid query yields one located row and one pin', async ({ page }) => {
    await submitSearch(page, 'ark:/28722/k2000hz7r');
    await waitSearchSettled(page);
    await waitPinsAtLeast(page, 1);

    const state = await searchState(page);
    // Real result, not a build failure.
    expect(state.resultsText).not.toMatch(/couldn't build|search error/i);

    const pinPids = (await pins(page)).map((p) => p.pid);
    const located = await locatedRowPids(page);
    const displayed = await displayedRowCount(page);

    expect(displayed).toBe(1);
    expect(pinPids.length).toBe(1);
    expect(sortJoin(pinPids)).toBe(sortJoin(located));
  });

  test('global-many: basalt pins spread over > 30° extent, capped at 50', async ({ page }) => {
    await submitSearch(page, 'basalt');
    await waitPinsAtLeast(page, 1);
    await waitSearchSettled(page);

    const pinList = await pins(page);
    expect(pinList.length).toBeGreaterThan(0);
    expect(pinList.length).toBeLessThanOrEqual(50);
    // Documented total (785) exceeds the LIMIT 50 cap, so it must bind exactly.
    expect(await displayedRowCount(page)).toBe(50);

    // Exact identity: pins are precisely the located displayed rows (same
    // assertion the local-many case makes — the plan requires it for "all four").
    const located = await locatedRowPids(page);
    expect(sortJoin(pinList.map((p) => p.pid))).toBe(sortJoin(located));

    const lats = pinList.map((p) => p.lat);
    const lngs = pinList.map((p) => p.lng);
    const latExtent = Math.max(...lats) - Math.min(...lats);
    const lngExtent = Math.max(...lngs) - Math.min(...lngs);
    // Globally distributed corpus → the pin cloud spans well past 30°.
    expect(Math.max(latExtent, lngExtent)).toBeGreaterThan(30);
  });

  test('zero: a no-hit query is a real zero (not a build failure) with no pins', async ({ page }) => {
    await submitSearch(page, 'xyzzyqqqplugh');
    await waitSearchSettled(page);

    const state = await searchState(page);
    // Distinguish a genuine empty result set from an infrastructure failure:
    // a real zero shows "No results", NOT "Search error"/"couldn't build".
    expect(state.resultsText).toMatch(/no results/i);
    expect(state.resultsText).not.toMatch(/couldn't build|search error/i);
    expect((await pins(page)).length).toBe(0);
  });

  test('new search replaces the PIN set', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    await waitPinsAtLeast(page, 1);
    const firstPinPids = (await pins(page)).map((p) => p.pid);
    expect(firstPinPids.length).toBeGreaterThan(0);
    expect(firstPinPids.length).toBeLessThanOrEqual(50);

    await submitSearch(page, 'basalt');
    // Wait for the count line to reflect the NEW term, then for pins to repopulate.
    await page.waitForFunction(() =>
      /results for "basalt"/i.test(document.getElementById('searchResults')?.textContent || ''),
      null, { timeout: 120_000 });
    await waitPinsAtLeast(page, 1);
    const secondPinPids = (await pins(page)).map((p) => p.pid);

    expect(secondPinPids.length).toBeGreaterThan(0);
    expect(secondPinPids.length).toBeLessThanOrEqual(50);
    // Disjoint corpora → the PIN set (not just the side panel) must change.
    expect(sortJoin(secondPinPids)).not.toBe(sortJoin(firstPinPids));
  });

  test('committed empty search clears the pins (snapshot lifecycle)', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    await waitPinsAtLeast(page, 1);
    expect((await pins(page)).length).toBeGreaterThan(0);

    // Empty submit is a committed clear path — doSearch clears the overlay AND
    // the results list before the too-short early return, so they clear TOGETHER
    // (Codex round-3: assert the list too, not just the pins).
    await submitSearch(page, '');
    await page.waitForFunction(() =>
      (window.__searchPins ? window.__searchPins().length : -1) === 0
      && document.querySelectorAll('#samplesSection .sample-row').length === 0,
      null, { timeout: 60_000 });
    expect((await pins(page)).length).toBe(0);
    expect(await displayedRowCount(page)).toBe(0);
  });

  test('Back after a pin click clears BOTH the list and the pins', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    await waitPinsAtLeast(page, 1);
    const beforePins = (await pins(page)).map((p) => p.pid);
    const displayedBefore = await displayedRowCount(page);
    expect(beforePins.length).toBeGreaterThan(0);
    expect(displayedBefore).toBeGreaterThan(0);

    // A result-pin click selects the sample and pushes a pid hash, while
    // PRESERVING the list and pins (verified here).
    const clicked = await page.evaluate(() => window.__clickSearchPin(0));
    expect(clicked).toBe(true);
    await page.waitForFunction(() => {
      const cs = document.getElementById('clusterSection');
      return cs && /<h4>\s*Sample\s*<\/h4>/i.test(cs.innerHTML);
    }, null, { timeout: 60_000 });
    expect((await pins(page)).length).toBe(beforePins.length);
    expect(await displayedRowCount(page)).toBe(displayedBefore);

    // Back → the no-selection hash → the hashchange handler clears BOTH the
    // preserved list and the pin overlay (the round-2 sync fix; regression guard).
    await page.goBack();
    await page.waitForFunction(() =>
      (window.__searchPins ? window.__searchPins().length : -1) === 0
      && document.querySelectorAll('#samplesSection .sample-row').length === 0,
      null, { timeout: 60_000 });
    expect((await pins(page)).length).toBe(0);
    expect(await displayedRowCount(page)).toBe(0);
  });

  test('selecting a located result row selects it AND preserves the list + pins', async ({ page }) => {
    await submitSearch(page, 'pottery Cyprus');
    await waitPinsAtLeast(page, 1);
    const before = (await pins(page)).map((p) => p.pid);
    const displayedBefore = await displayedRowCount(page);

    // Pick a DEMONSTRABLY LOCATED row (numeric data-lat/lng, not the string
    // "null") — a coord-less row's handler returns immediately, so clicking it
    // would prove nothing (Codex round-2 P2).
    const located = await page.$$eval('#samplesSection .sample-row', (els) =>
      els
        .filter((e) => {
          const la = e.dataset.lat, ln = e.dataset.lng;
          return la && la !== 'null' && la !== 'undefined'
              && ln && ln !== 'null' && ln !== 'undefined';
        })
        .map((e) => ({ pid: e.dataset.pid, label: (e.querySelector('.sample-label')?.textContent || '').trim() })));
    expect(located.length).toBeGreaterThan(0);
    const target = located[0];

    // Click a NON-LINK child (the source badge) so the row handler runs — its
    // own handler bails on clicks that land on the <a> label.
    await page.locator(`#samplesSection .sample-row[data-pid="${target.pid}"] .source-badge`).first().click();

    // Assert the selection ACTUALLY happened (the sample card now shows this
    // sample) with a condition-based wait BEFORE checking preservation.
    await page.waitForFunction((label) => {
      const cs = document.getElementById('clusterSection');
      if (!cs) return false;
      return /<h4>\s*Sample\s*<\/h4>/i.test(cs.innerHTML) && cs.textContent.includes(label);
    }, target.label, { timeout: 60_000 });

    // Row selection must NOT tear down the results list or its pin snapshot.
    const after = (await pins(page)).map((p) => p.pid);
    expect(await displayedRowCount(page)).toBe(displayedBefore);
    expect(sortJoin(after)).toBe(sortJoin(before));
  });
});
