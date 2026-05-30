// A1 (#234 Step 4) deterministic verify harness.
//
// Condition-based (no fixed sleeps), against a LOCAL parquet mirror so the
// loop is fast and repeatable. Run pattern:
//
//   1. mirror parquets once:  ls docs/data/*.parquet  (see SESSION_SUMMARY)
//   2. python3 dev_server.py --dir docs --port 8099   (RANGE-capable; 206)
//   3. node tests/playwright/a1-verify.mjs            (or via @playwright/test)
//
// The big win is LOAD ONCE, then drive searches IN-PAGE: cold init is
// ~40s (DuckDB-WASM+Cesium+OJS, init-dominated, mirror can't help), but each
// in-page search then hits the local mirror fast. So this script pays init
// once and can loop searches via page.evaluate without reloading.
//
// Asserts the A1 coherence invariant: when a search is committed, the TABLE,
// the globe MODE (must be 'point'), and the rendered sample points all
// reflect the search — not unfiltered clusters.

import { chromium } from 'playwright';

const BASE = process.env.A1_BASE
  || 'http://localhost:8099/explorer.html?data_base=/data&debug=a1&sources=OPENCONTEXT%2CGEOME%2CSMITHSONIAN';
const TERM = process.env.A1_TERM || 'bucchero';
// Boot at high altitude (cluster) WITHOUT a search, so we test C3 forcing
// point mode from cluster via an in-page search (the failing case).
const URL = `${BASE}#v=1&lat=43.15&lng=11.40&alt=9000000`;

// Default headed (real flyTo, what the A1 work is verified against). Set
// HEADLESS=1 for reliable automated/CI runs — headless pages are always
// "active", so they're immune to the backgrounded-window rAF freeze that
// hangs an unfocused headed window mid-init.
const browser = await chromium.launch({ headless: process.env.HEADLESS === '1' });
const page = await browser.newPage();
page.on('console', (m) => { if (/A1|point mode|Discarding/.test(m.text())) console.log('  page>', m.text()); });

console.log('Loading (cold init ~40s)…', URL);
await page.goto(URL, { waitUntil: 'domcontentloaded' });

// Wait for the OJS graph + DuckDB to be live (search machinery installed).
await page.waitForFunction(
  () => typeof window.a1dbg === 'function' && !!window.__a1globe && !!document.querySelector('#sampleSearch'),
  null, { timeout: 180_000 });
console.log('App live. Boot mode:', await page.evaluate(() => window.__a1globe?.()));

// Drive a search IN-PAGE (type + Enter on the map search input).
await page.fill('#sampleSearch', TERM);
await page.press('#sampleSearch', 'Enter');

// Wait on the filter actually building (condition, not sleep).
await page.waitForFunction(
  (t) => window.__searchFilter?.active === true && window.__searchFilter?.term === t && window.__searchFilter?.total > 0,
  TERM, { timeout: 120_000 });

// Wait for the globe to settle into point mode with filtered dots.
await page.waitForFunction(() => {
  const g = window.__a1globe?.();
  return g && g.mode === 'point' && g.samplePointsShown === true && g.samplePointsLen > 0;
}, null, { timeout: 60_000 }).catch(() => console.log('  !! globe did NOT reach filtered point mode'));

const state = await page.evaluate(() => ({
  search: window.__searchFilter,
  globe: window.__a1globe?.(),
  tableMeta: document.getElementById('tableMeta')?.textContent?.trim(),
  a1log: window.__a1log,
}));

console.log('\n=== RESULT ===');
console.log(JSON.stringify(state, null, 2));

const ok =
  state.search?.active === true &&
  state.globe?.mode === 'point' &&
  state.globe?.samplePointsShown === true &&
  state.globe?.h3PointsShown === false &&
  state.globe?.samplePointsLen > 0 &&
  state.globe?.samplePointsLen <= state.search?.total;

console.log(ok ? '\n✅ A1 COHERENT: table + globe both filtered to the search.'
              : '\n❌ A1 INCOHERENT: see globe.mode / samplePoints above.');

// Keep the browser open for manual poking unless A1_CLOSE=1.
if (process.env.A1_CLOSE) await browser.close();
