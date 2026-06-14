// Explorer smoke gate (#249 PR 1) — the minimal "is the explorer alive?"
// set that CI runs on every PR touching the explorer, BEFORE any refactor
// of explorer.qmd lands.
//
// Scope is deliberately tiny (one assertion per concern):
//   1. the page loads without an uncaught JS exception,
//   2. the Cesium map canvas appears with non-zero size,
//   3. the facet sidebar renders (static source-legend rows),
//   4. the search box is present.
//
// What this does NOT cover: data correctness. The explorer streams
// multi-hundred-MB parquet from data.isamples.org via DuckDB-WASM range
// requests; this gate must stay green even when that load is slow or the
// network is constrained, so nothing here waits on facet counts, sample
// dots, or search results. Deeper data-dependent specs live in the other
// files in this directory and run on demand, and the pre-deploy gate in
// quarto-pages.yml (tests/test_smoke.py) separately asserts DuckDB-WASM
// liveness before anything reaches production.
//
// Per the hard-won lesson documented in tests/test_smoke.py: ONE fresh
// context, ONE navigation, poll-for-readiness. Rapid reloads exhaust the
// DuckDB-WASM worker and produce false failures — so the four tests share
// a single page load (serial mode) instead of navigating four times.

const { test, expect } = require('@playwright/test');
const { explorerUrl } = require('./helpers/url');

test.describe('Explorer smoke gate (#249)', () => {
  test.describe.configure({ mode: 'serial' });

  /** @type {import('@playwright/test').Page} */
  let page;
  /** @type {string[]} */
  let pageErrors;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      // The gate asserts on our page, not on TLS. Sandboxed/proxied dev
      // environments MITM outbound HTTPS (Cesium CDN, data.isamples.org)
      // with a CA Chromium doesn't trust; without this the page can never
      // boot there. No-op on a clean network like GitHub Actions.
      ignoreHTTPSErrors: true,
    });
    page = await context.newPage();
    pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(String(err)));
    // OJS swallows cell exceptions: a crashed cell (undefined symbol,
    // syntax slip in explorer.qmd) logs "Error evaluating OJS cell" to the
    // console instead of firing pageerror. That signature IS the "explorer
    // is dead" signal this gate exists for, so collect it too.
    page.on('console', (msg) => {
      if (msg.type() === 'error' && /Error evaluating OJS cell/i.test(msg.text())) {
        pageErrors.push(msg.text().slice(0, 500));
      }
    });

    await page.goto(explorerUrl(), {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
  });

  test.afterAll(async () => {
    await page?.context().close();
  });

  // The page is shared across the serial tests, so an async error that
  // fires AFTER the first test (late OJS cell crash, runtime regression
  // surfacing during the canvas/sidebar/search checks) must still fail
  // the gate — assert the accumulator after every test, draining it so
  // each error is reported exactly once.
  test.afterEach(() => {
    const errs = pageErrors.splice(0);
    expect(errs, `uncaught page errors:\n${errs.join('\n')}`).toEqual([]);
  });

  test('explorer loads without uncaught JS errors', async () => {
    await expect(page).toHaveTitle(/Interactive Explorer/i, { timeout: 30000 });
    // The Cesium container is static HTML in explorer.qmd — if it is
    // missing, the render itself is broken (not just slow data).
    await expect(page.locator('#cesiumContainer')).toBeAttached({ timeout: 30000 });
    // Give the boot path a moment to surface an early uncaught exception
    // (OJS cell crash, undefined symbol) without waiting on data —
    // afterEach below does the actual assertion for this and every test.
    await page.waitForTimeout(3000);
  });

  test('map canvas appears with non-zero size', async () => {
    const canvas = page.locator('.cesium-viewer .cesium-widget canvas');
    await expect(canvas).toBeAttached({ timeout: 60000 });
    // A 0x0 canvas means the widget mounted but the globe never sized —
    // the "container but no globe" failure mode test_smoke.py documents.
    await expect
      .poll(async () => {
        const box = await canvas.boundingBox();
        return box ? Math.min(box.width, box.height) : 0;
      }, { timeout: 30000 })
      .toBeGreaterThan(0);
  });

  test('facet sidebar renders source facet rows', async () => {
    // The four source rows are static HTML in explorer.qmd, so this
    // asserts the sidebar structure rendered — it does NOT wait for the
    // DuckDB-WASM facet-count fill (data-dependent, excluded from smoke).
    const sourceRows = page.locator('.facet-row[data-facet="source"]');
    await expect(sourceRows.first()).toBeVisible({ timeout: 30000 });
    expect(await sourceRows.count()).toBeGreaterThanOrEqual(4);
  });

  test('search box is present', async () => {
    // Post-#266 there is exactly one search input: the in-map overlay.
    await expect(page.locator('#sampleSearch')).toBeVisible({ timeout: 30000 });
    await expect(page.locator('#sampleSearch')).toHaveCount(1);
  });
});
