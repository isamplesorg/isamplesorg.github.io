// #248 Flavor A (`described-by=<concept-uri>`) deterministic verify harness.
//
// Sibling of a1-verify.mjs — same LOAD-ONCE-then-assert pattern against the
// LOCAL parquet mirror. Verifies the concept-URI deep link drives EVERY
// surface coherently (the A1 invariant, but for the concept producer of
// search_pids), and that committing a text search afterward flips the URL
// from `described-by=` to `search=` (mutual exclusivity).
//
// Run pattern (same as a1-verify):
//   1. mirror parquets once:  ls docs/data/*.parquet
//   2. python3 dev_server.py --dir docs --port 8099
//   3. HEADLESS=1 node tests/playwright/described-by-verify.mjs
//
// HEADLESS=1 is strongly recommended — headed backgrounded windows freeze rAF
// (Cesium camera never settles), corrupting globe-mode observations.

import { chromium } from 'playwright';

// A well-populated, clearly cross-domain concept (biology — "Whole organism
// material sample"), to tell the iSamples cross-domain story, not archaeology.
const URI = process.env.DB_URI
  || 'https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/wholeorganism';
const EXPECT_LABEL = process.env.DB_LABEL || 'Whole organism material sample';

const BASE = process.env.A1_BASE
  || 'http://localhost:8099/explorer.html?data_base=/data&debug=a1&sources=OPENCONTEXT%2CGEOME%2CSMITHSONIAN';
// Boot at high altitude (cluster) so we test that the concept deep link forces
// filtered point mode from cluster — the same hard case a1-verify covers.
const URL = `${BASE}&described-by=${encodeURIComponent(URI)}#v=1&lat=20&lng=0&alt=9000000`;

const browser = await chromium.launch({ headless: process.env.HEADLESS === '1' });
const page = await browser.newPage();
page.on('console', (m) => { if (/A1|point mode|concept|Discarding|#248/.test(m.text())) console.log('  page>', m.text()); });

console.log('Loading (cold init ~40s)…', URL);
await page.goto(URL, { waitUntil: 'domcontentloaded' });

// App live (OJS graph + DuckDB + search machinery installed).
await page.waitForFunction(
  () => typeof window.a1dbg === 'function' && !!window.__a1globe && !!document.querySelector('#sampleSearch'),
  null, { timeout: 180_000 });
console.log('App live. Boot mode:', await page.evaluate(() => window.__a1globe?.()));

// The deep link should auto-commit the concept filter at boot (kind:'concept').
await page.waitForFunction(
  () => window.__searchFilter?.active === true
     && window.__searchFilter?.kind === 'concept'
     && window.__searchFilter?.total > 0,
  null, { timeout: 120_000 });

// Globe settles into filtered point mode (clusters can't be concept-filtered).
await page.waitForFunction(() => {
  const g = window.__a1globe?.();
  return g && g.mode === 'point' && g.samplePointsShown === true && g.samplePointsLen > 0;
}, null, { timeout: 60_000 }).catch(() => console.log('  !! globe did NOT reach filtered point mode'));

// The side-panel render runs AFTER applySearchFilterChange returns (a separate
// LIMIT-50 SELECT off search_pids), so wait for the concept heading to paint
// before snapshotting — otherwise we race the "Filtering by concept…" interim.
await page.waitForFunction(() => {
  const h = document.querySelector('#samplesSection .search-results-heading');
  return h && /Samples described by:/.test(h.textContent || '');
}, null, { timeout: 60_000 }).catch(() => console.log('  !! concept side panel did NOT render'));

const state = await page.evaluate(() => ({
  search: window.__searchFilter,
  globe: window.__a1globe?.(),
  tableMeta: document.getElementById('tableMeta')?.textContent?.trim(),
  panelHeading: document.querySelector('#samplesSection .search-results-heading')?.textContent?.trim(),
  resultsLine: document.getElementById('searchResults')?.textContent?.trim(),
  urlSearch: location.search,
}));

console.log('\n=== CONCEPT DEEP-LINK RESULT ===');
console.log(JSON.stringify(state, null, 2));

const conceptOk =
  state.search?.active === true &&
  state.search?.kind === 'concept' &&
  state.search?.uri === URI &&
  state.globe?.mode === 'point' &&
  state.globe?.samplePointsShown === true &&
  state.globe?.h3PointsShown === false &&
  state.globe?.samplePointsLen > 0 &&
  state.globe?.samplePointsLen <= state.search?.total &&
  /Samples described by:/.test(state.panelHeading || '') &&
  (state.panelHeading || '').includes(EXPECT_LABEL) &&
  /described-by=/.test(state.urlSearch) &&
  !/[?&]search=/.test(state.urlSearch);

console.log(conceptOk
  ? '\n✅ #248 CONCEPT COHERENT: globe + panel + URL all reflect the concept filter.'
  : '\n❌ #248 INCOHERENT: see fields above.');

// Mutual exclusivity: now commit a free-text search; described-by= must drop
// out of the URL and the filter kind must flip to 'text'.
await page.fill('#sampleSearch', 'pottery');
await page.press('#sampleSearch', 'Enter');
await page.waitForFunction(
  () => window.__searchFilter?.active === true
     && window.__searchFilter?.kind === 'text'
     && window.__searchFilter?.term === 'pottery',
  null, { timeout: 120_000 }).catch(() => console.log('  !! text search did not take over'));

const after = await page.evaluate(() => ({
  kind: window.__searchFilter?.kind,
  term: window.__searchFilter?.term,
  urlSearch: location.search,
}));
console.log('\n=== AFTER TEXT SEARCH (mutual exclusivity) ===');
console.log(JSON.stringify(after, null, 2));

const mutexOk =
  after.kind === 'text' &&
  /[?&]search=pottery/.test(after.urlSearch) &&
  !/described-by=/.test(after.urlSearch);

console.log(mutexOk
  ? '\n✅ MUTUAL EXCLUSIVITY: text search took over; described-by= cleared from URL.'
  : '\n❌ MUTUAL EXCLUSIVITY FAILED: see fields above.');

const ok = conceptOk && mutexOk;
console.log(ok ? '\n✅✅ #248 FLAVOR A VERIFIED.' : '\n❌ #248 verify FAILED.');

if (process.env.A1_CLOSE) await browser.close();
process.exitCode = ok ? 0 : 1;
