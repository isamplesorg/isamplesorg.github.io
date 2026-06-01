// Headless shakedown probe: confirms the local mirror boots on HTTP/1.1 and
// that a committed search exercises the big-file range path. Does NOT assert
// A1 globe coherence (that's the known logjam) — only boot + search timing.
import { chromium } from 'playwright';

const BASE = 'http://localhost:8099/explorer.html?data_base=/data&debug=a1&sources=OPENCONTEXT%2CGEOME%2CSMITHSONIAN';
const URL = `${BASE}#v=1&lat=43.15&lng=11.40&alt=9000000`;
const TERM = 'bucchero';
const t0 = performance.now();
const sec = () => ((performance.now() - t0) / 1000).toFixed(1) + 's';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
page.on('pageerror', e => console.log('  [pageerror]', String(e).slice(0, 120)));

console.log(`[${sec()}] goto`, URL);
await page.goto(URL, { waitUntil: 'domcontentloaded' });

await page.waitForFunction(
  () => typeof window.a1dbg === 'function' && !!window.__a1globe && !!document.querySelector('#sampleSearch'),
  null, { timeout: 90_000 });
console.log(`[${sec()}] APP LIVE — boot globe:`, await page.evaluate(() => window.__a1globe?.()));

await page.fill('#sampleSearch', TERM);
await page.press('#sampleSearch', 'Enter');
console.log(`[${sec()}] search submitted: "${TERM}" (scans sample_facets_v2.parquet)`);

await page.waitForFunction(
  (t) => window.__searchFilter?.active === true && window.__searchFilter?.term === t && window.__searchFilter?.total > 0,
  TERM, { timeout: 120_000 });
const st = await page.evaluate(() => ({ search: window.__searchFilter, globe: window.__a1globe?.() }));
console.log(`[${sec()}] SEARCH FILTER BUILT — total pids:`, st.search?.total, ' globe:', JSON.stringify(st.globe));

await browser.close();
console.log(`[${sec()}] done`);
