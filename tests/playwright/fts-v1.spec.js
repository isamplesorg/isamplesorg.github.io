// #171: substrate search path (?fts=v1) — end-to-end against the published
// index at data.isamples.org/isamples_202608_search_index_v1/.
//
// Run:  BASE_URL=https://rdhyee.github.io/isamplesorg.github.io \
//       npx playwright test tests/playwright/fts-v1.spec.js
//
// Ground truths are properties of the 202608 index (see PR #329's
// committed build stats): 'axial seamount summit caldera' → 284;
// 'pottery Cyprus' → 1,305; 'basalt' alone → 785.

const { test, expect } = require('@playwright/test');

const BASE = process.env.BASE_URL || 'https://rdhyee.github.io/isamplesorg.github.io';
const URL = `${BASE}/explorer.html?fts=v1`;

async function bootAndSearch(page, term) {
  await page.fill('#sampleSearch', term);
  await page.locator('#searchSubmitBtn').first().click();
  await page.waitForFunction(
    (t) => window.__searchFilter && window.__searchFilter.term === t
        && window.__searchFilter.substrate === true,
    term, { timeout: 120_000 });
  return page.evaluate(() => ({
    total: window.__searchFilter.total,
    mode: window.__searchFilter.substrateMode,
    ignored: window.__searchFilter.ignoredCommon || [],
    expectedBytes: window.__searchFilter.expectedBytes,
  }));
}

test.describe('substrate search (?fts=v1)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(URL, { timeout: 90_000 });
    await page.waitForSelector('.samples-table tbody tr[data-pid]', { timeout: 120_000 });
  });

  test('multi-term place query matches ILIKE ground truth', async ({ page }) => {
    const r = await bootAndSearch(page, 'axial seamount summit caldera');
    expect(r.mode).toBe('normal');
    expect(r.total).toBe(284);
  });

  test('keyword-concept recall: pottery Cyprus (the #326-class case)', async ({ page }) => {
    const r = await bootAndSearch(page, 'pottery Cyprus');
    expect(r.mode).toBe('normal');
    expect(r.total).toBe(1305);
    expect(r.expectedBytes).toBeGreaterThan(0);
    expect(r.expectedBytes).toBeLessThan(6_000_000);
  });

  test('common term dropped from AND with disclosure', async ({ page }) => {
    const r = await bootAndSearch(page, 'material basalt');
    expect(r.mode).toBe('normal');
    expect(r.ignored).toEqual(['material']);
    expect(r.total).toBe(785);   // == 'basalt' alone
    // The §3/§6 disclosure must be user-visible in the results heading.
    await page.waitForFunction(() =>
      /common word/i.test(document.getElementById('samplesSection')?.textContent || ''),
      null, { timeout: 60_000 });
  });

  test('all-common query engages topk mode (approximation, not error)', async ({ page }) => {
    const r = await bootAndSearch(page, 'material sample');
    expect(r.mode).toBe('topk');
    // total may legitimately be small or 0 (top-500 intersection) — the
    // assertion is that the MODE engaged and nothing crashed. #172's
    // benchmark quantifies the empty-rate; union-rank is the candidate fix.
  });

  test('all-stopword query → controlled empty', async ({ page }) => {
    await page.fill('#sampleSearch', 'a the of');
    await page.locator('#searchSubmitBtn').first().click();
    await page.waitForFunction(() =>
      window.__searchFilter && window.__searchFilter.substrate === true
      && window.__searchFilter.active === false, null, { timeout: 60_000 });
    const note = await page.evaluate(() => window.__searchFilter.note || '');
    expect(note).toMatch(/common words/i);
    // The copy must be USER-VISIBLE (Codex review), not just internal state.
    await page.waitForFunction(() =>
      /common words/i.test(document.getElementById('searchResults')?.textContent || '')
      || /common words/i.test(document.getElementById('samplesSection')?.textContent || ''),
      null, { timeout: 60_000 });
  });

  test('default path untouched: no fts param → interim search', async ({ page }) => {
    // The INTERIM path cold-downloads the 69 MB facets parquet — the one
    // test here that can't fit the 30 s config default. (The five substrate
    // tests above all do; that asymmetry is the point of #171.)
    test.setTimeout(240_000);
    await page.goto(`${BASE}/explorer.html`, { timeout: 90_000 });
    await page.waitForSelector('.samples-table tbody tr[data-pid]', { timeout: 120_000 });
    await page.fill('#sampleSearch', 'basalt');
    await page.locator('#searchSubmitBtn').first().click();
    await page.waitForFunction(() =>
      window.__searchFilter && window.__searchFilter.active, null, { timeout: 150_000 });
    const substrate = await page.evaluate(() => window.__searchFilter.substrate);
    expect(substrate).toBeFalsy();
  });
});
