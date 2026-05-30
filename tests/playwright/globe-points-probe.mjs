// Globe point-load diagnosis: does a committed search render sample points,
// and does the answer depend on camera ALTITUDE? Hypothesis: at whole-globe
// altitude, getViewportBounds() (computeViewRectangle) returns null and
// loadViewportSamples() bails → 0 points, even though search forced point mode.
//
// Usage: node globe-points-probe.mjs <alt> <lat> <lng>
import { chromium } from 'playwright';

const ALT = process.argv[2] || '9000000';
const LAT = process.argv[3] || '43.15';
const LNG = process.argv[4] || '11.40';
const BASE = 'http://localhost:8099/explorer.html?data_base=/data&debug=a1&sources=OPENCONTEXT%2CGEOME%2CSMITHSONIAN';
const URL = `${BASE}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT}`;
const TERM = 'bucchero';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto(URL, { waitUntil: 'domcontentloaded' });
await page.waitForFunction(
  () => typeof window.a1dbg === 'function' && !!window.__a1globe && !!document.querySelector('#sampleSearch'),
  null, { timeout: 90_000 });

// reset the event log so we only capture the search→point-load sequence
await page.evaluate(() => { window.__a1log = []; });
await page.fill('#sampleSearch', TERM);
await page.press('#sampleSearch', 'Enter');
await page.waitForFunction(
  (t) => window.__searchFilter?.active === true && window.__searchFilter?.term === t && window.__searchFilter?.total > 0,
  TERM, { timeout: 120_000 });
// give the point load a generous window to run/settle
await page.waitForTimeout(6000);

const out = await page.evaluate(() => ({
  globe: window.__a1globe?.(),
  searchTotal: window.__searchFilter?.total,
  // event types in order, plus any point-load events with their payloads
  events: (window.__a1log || []).map(e => e.event),
  pointLoadEvents: (window.__a1log || []).filter(e => /point-load/.test(e.event)),
}));

console.log(`\n=== alt=${ALT} lat=${LAT} lng=${LNG} ===`);
console.log('searchTotal :', out.searchTotal);
console.log('globe       :', JSON.stringify(out.globe));
console.log('events      :', out.events.join(' → '));
console.log('point-load  :', JSON.stringify(out.pointLoadEvents, null, 2));
await browser.close();
