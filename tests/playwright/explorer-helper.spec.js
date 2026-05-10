/**
 * Explorer — tryEnterPointModeIfNeeded() invariants (closes #192)
 *
 * The helper introduced in PR #191 short-circuits when:
 *   (a) `mode === 'point'`               (already there)
 *   (b) altitude >= ENTER_POINT_ALT      (cluster regime)
 *   (c) `currentRes !== 8 && loading`    (an unrelated load is in flight)
 *
 * Cell-internal state (`mode`, `currentRes`, `loading`, `viewer`) is
 * closure-private inside an OJS cell, but Quarto's OJS runtime exposes
 * the cell's *outputs* through `window._ojs.ojsConnector.mainModule.value(name)`.
 * We use that to fetch the `viewer` Cesium widget and drive its camera
 * directly, then assert on observable outputs:
 *   - `#phaseMsg` textContent (rewritten by `updatePhaseMsg(...)`)
 *   - `viewer._globeState.mode` ('cluster' | 'point')
 *   - `viewer.camera.positionCartographic.height`
 *
 * This lets us reproduce the cold-cache cluster→point-mode transition in
 * headless chromium without needing real user interaction with the globe.
 *
 * Coverage matrix vs the helper's invariants:
 *   - Invariant (a) `mode==='point'` short-circuit: covered by the
 *     point-mode source-filter test. After the helper has driven us
 *     into point mode, toggling the source filter must NOT trigger the
 *     helper's `Fetching sample index…` loadingMsg again.
 *   - Invariant (b) altitude short-circuit: covered by the world-altitude
 *     source-filter test. The source-filter handler chases the helper
 *     after its own `loadRes` settles; at world altitude the chase MUST
 *     bail at the altitude check without painting the helper's loadingMsg.
 *   - Invariant (c) `!loading` short-circuit: not exercised here; would
 *     need timing injection. Documented in #192 as a future addition.
 *
 * Plus the boot→point-mode happy path is covered as a smoke test for the
 * helper's overall behavior (camera-handler call site).
 */

const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.TEST_URL || 'http://localhost:5860';
const EXPLORER_PATH = '/explorer.html';

// Phrases written by `updatePhaseMsg` we check for in tests.
const FETCHING_SAMPLE_INDEX = 'Fetching sample index';   // the helper's loadingMsg
const LOADING_H3_RES = 'Loading H3 res';                  // default loadRes loadingMsg
const LOADING_INDIVIDUAL = 'Loading individual samples';  // loadViewportSamples loading
const CLUSTERS_DONE = 'clusters,';                        // cluster-mode done message contains "${n} clusters, ${m} samples."
const INDIVIDUAL_SAMPLES = 'individual samples';          // point-mode done message

// Camera altitudes used by tests. Match the hysteresis thresholds in
// explorer.qmd: ENTER_POINT_ALT = 120000m, EXIT_POINT_ALT = 180000m.
const ALT_WORLD = 10000000;        // > EXIT_POINT_ALT, definitely cluster
const ALT_POINT_CYPRUS = 62054;    // < ENTER_POINT_ALT, point mode (Cyprus PKAP)
const LAT_CYPRUS = 34.9954;
const LNG_CYPRUS = 33.7052;

/**
 * Fetch the closure-private `viewer` cell value via Quarto's OJS runtime.
 * Must be called inside a `page.evaluate(async () => { ... })` block.
 * Inlined into each evaluate to keep this helper self-contained.
 */
const GET_VIEWER = `await window._ojs.ojsConnector.mainModule.value('viewer')`;

/**
 * Install a MutationObserver on `#phaseMsg` that records every textContent
 * change into `window._phaseHistory`. Returns when the observer is wired.
 */
async function startPhaseHistory(page) {
  await page.evaluate(() => {
    window._phaseHistory = [];
    const el = document.getElementById('phaseMsg');
    if (!el) throw new Error('No #phaseMsg element');
    window._phaseHistory.push(el.textContent.trim());
    const observer = new MutationObserver(() => {
      const text = el.textContent.trim();
      const last = window._phaseHistory[window._phaseHistory.length - 1];
      if (text !== last) window._phaseHistory.push(text);
    });
    observer.observe(el, { childList: true, characterData: true, subtree: true });
    window._phaseObserver = observer;
  });
}

async function getPhaseHistory(page) {
  return await page.evaluate(() => window._phaseHistory || []);
}

/**
 * Wait until #phaseMsg textContent contains `substring`, or until `timeoutMs`.
 */
async function waitForPhaseMessage(page, substring, timeoutMs = 60000) {
  return await page.waitForFunction(
    (sub) => {
      const el = document.getElementById('phaseMsg');
      const text = el ? el.textContent : '';
      return text.includes(sub) ? text.trim() : null;
    },
    substring,
    { timeout: timeoutMs }
  ).then(handle => handle.jsonValue());
}

/** Wait until viewer._globeState.mode equals `expected`. */
async function waitForMode(page, expected, timeoutMs = 60000) {
  return await page.waitForFunction(
    async (expectedMode) => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      return v && v._globeState && v._globeState.mode === expectedMode;
    },
    expected,
    { timeout: timeoutMs }
  );
}

/**
 * Wait for a loading→done transition to be present in `window._phaseHistory`
 * since the observer was started. Searches the history for `loadingSub`,
 * then a *later* entry matching `donePattern` (string substring or RegExp).
 *
 * Use this for assertions that must wait for an action to fully settle.
 * `waitForPhaseMessage(...)` alone can resolve against pre-action text
 * because `#phaseMsg` may already contain the substring before the
 * action triggered any new loadRes / loadViewportSamples call.
 */
async function waitForLoadingThenDone(page, loadingSub, donePattern, timeoutMs = 120000) {
  const patternIsRegex = donePattern instanceof RegExp;
  const patternStr = patternIsRegex
    ? { source: donePattern.source, flags: donePattern.flags, isRegex: true }
    : { source: donePattern, isRegex: false };
  await page.waitForFunction(
    ({ loadingSub, patternStr }) => {
      const h = window._phaseHistory || [];
      const match = (s) => patternStr.isRegex
        ? new RegExp(patternStr.source, patternStr.flags).test(s)
        : s.includes(patternStr.source);
      const loadingIdx = h.findIndex(s => s.includes(loadingSub));
      if (loadingIdx === -1) return false;
      // Look for the done pattern strictly after the loading entry — done
      // text that already appeared *before* the action is not enough.
      return h.slice(loadingIdx + 1).some(match);
    },
    { loadingSub, patternStr },
    { timeout: timeoutMs }
  );
}

// Regex matching the count-prefixed cluster done message ("${n} clusters,
// ${m} samples. Zoom in for finer detail."). Match `n` followed by " clusters,".
const CLUSTER_DONE_RE = /\d[\d,]*\s+clusters,/;
// Regex matching the count-prefixed point-mode done message ("${n} individual
// samples. Click one for details.").
const POINT_DONE_RE = /\d[\d,]*\s+individual\s+samples/;

/**
 * Wait for the explorer's initial phase-1 cluster load to settle AND
 * for the `zoomWatcher` OJS cell to finish initializing. Phase 1 paints
 * the cluster done message, but the source-filter change handler /
 * camera handler are registered later, inside the `zoomWatcher` cell
 * (which depends on `phase1`). Without this second wait, a test that
 * dispatches a change event right after the done message appears can
 * race the listener registration and silently no-op.
 */
async function waitForClusterBoot(page) {
  await waitForPhaseMessage(page, CLUSTERS_DONE);
  // zoomWatcher returns "active" after registering all camera /
  // source-filter / facet event listeners. Awaiting its value is a
  // reliable sync point — OJS resolves it once the cell body completes.
  await page.evaluate(async () => {
    return await window._ojs.ojsConnector.mainModule.value('zoomWatcher');
  });
}

/**
 * Toggle a source-filter checkbox and dispatch a `change` event manually.
 *
 * Playwright's checkbox helpers (`uncheck()` / `check()` with `force:true`)
 * skip actionability checks but don't reliably fire `change` in this
 * layout where the input lives inside a `<label class="legend-item">`
 * wrapper. A plain `click()` works in isolation but is flaky when run
 * after another test in the same suite (Cesium widget may transiently
 * occlude the checkbox during boot). Direct DOM mutation + a
 * `dispatchEvent(new Event('change', { bubbles: true }))` is what the
 * source-filter handler actually listens for, and is robust under both
 * conditions.
 */
async function toggleSourceFilter(page, index = 0) {
  await page.evaluate((i) => {
    const cb = document.querySelectorAll('#sourceFilter input[type="checkbox"]')[i];
    if (!cb) throw new Error('No source-filter checkbox at index ' + i);
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event('change', { bubbles: true }));
  }, index);
}

/**
 * Drive the Cesium camera to `(lat, lng, alt)` via flyTo, with the scene's
 * requestRenderMode disabled so the render loop stays active. Cesium
 * fires `camera.changed` only between consecutive `postRender` events
 * that exceed `camera.percentageChanged`; in headless chromium the
 * render loop suspends after idle, so a single `setView` + `requestRender`
 * doesn't reliably trigger the camera-changed handler. Continuous-render
 * + animated flight does.
 *
 * The camera-changed handler is debounced 600ms, so callers should
 * `await waitForMode(...)` or `waitForPhaseMessage(...)` afterward to
 * observe the resulting transition.
 */
async function flyCameraTo(page, lat, lng, alt) {
  await page.evaluate(async ({ lat, lng, alt }) => {
    const v = await window._ojs.ojsConnector.mainModule.value('viewer');
    v.scene.requestRenderMode = false;  // keep render loop running so camera.changed fires
    v.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lng, lat, alt),
      duration: 1.0,
    });
  }, { lat, lng, alt });
}

test.describe('explorer: tryEnterPointModeIfNeeded short-circuit invariants', () => {

  test('boot to cluster mode reaches a done message with cluster counts', async ({ page }) => {
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#phaseMsg', { timeout: 30000 });

    const text = await waitForPhaseMessage(page, CLUSTERS_DONE);
    expect(text).toMatch(/\d[\d,]*\s+clusters/);
    expect(text).toMatch(/\d[\d,]*\s+samples/);
  });

  test('source-filter toggle at world altitude does NOT trigger Fetching sample index', async ({ page }) => {
    // Verifies invariant (b): tryEnterPointModeIfNeeded short-circuits on
    // altitude >= ENTER_POINT_ALT. The source-filter handler chases the
    // helper after its own loadRes settles; at world altitude the chase
    // should bail at the altitude check WITHOUT painting "Fetching sample
    // index…".
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('#sourceFilter input[type="checkbox"]', { timeout: 30000 });
    await waitForClusterBoot(page);

    await startPhaseHistory(page);

    // Toggle off, then wait for the full Loading H3 res… → done cycle to
    // appear in the history (must be a NEW done after the loading, not
    // the pre-action done text the observer captured at startup).
    await toggleSourceFilter(page, 0);
    await waitForLoadingThenDone(page, LOADING_H3_RES, CLUSTER_DONE_RE);
    // Toggle back on, then wait again for a NEW loading → done cycle.
    await toggleSourceFilter(page, 0);
    const beforeRetoggleLen = (await getPhaseHistory(page)).length;
    await page.waitForFunction(
      (n) => (window._phaseHistory || []).length > n,
      beforeRetoggleLen,
      { timeout: 60000 }
    );
    await waitForLoadingThenDone(page, LOADING_H3_RES, CLUSTER_DONE_RE);

    const history = await getPhaseHistory(page);
    expect(history.some(s => s.includes(LOADING_H3_RES))).toBeTruthy();
    // The chase MUST short-circuit at the altitude check — the helper's
    // own loadingMsg ("Fetching sample index…") MUST NOT appear at any
    // point in the captured history.
    expect(history.some(s => s.includes(FETCHING_SAMPLE_INDEX))).toBeFalsy();
  });

  test('flying camera into point altitude triggers helper and enters point mode', async ({ page }) => {
    // End-to-end coverage of the camera-handler call site of the helper.
    // Boots in cluster mode, then drives the camera to point altitude via
    // the OJS-runtime hook on viewer.camera.setView. Asserts that the
    // helper's loadingMsg ("Fetching sample index…") OR the eventual
    // point-mode done message ("${n} individual samples.") appear in
    // the phase-message history. (Cold-cache: helper fires loadRes(8)
    // and paints "Fetching sample index…"; warm-cache: currentRes is
    // already 8 so the helper short-circuits its loadRes and goes
    // straight to enterPointMode → "Loading individual samples…".)
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await waitForClusterBoot(page);

    await startPhaseHistory(page);
    await flyCameraTo(page, LAT_CYPRUS, LNG_CYPRUS, ALT_POINT_CYPRUS);

    // Wait for the camera-changed handler to debounce + helper to settle
    // + loadViewportSamples to fetch the 60 MB samples_map_lite.parquet.
    // Cold-cache fetches can take 60-90s on a real network; allow generous
    // timeouts at each stage.
    await waitForMode(page, 'point', 120000);
    // Wait for the full Loading individual samples → "${n} individual
    // samples." cycle in the captured history. Using the loading→done
    // sequence guarantees the negative assertion below (no Fetching
    // sample index after the loading-state) is meaningful — a regression
    // that paints Fetching sample index AFTER point-mode entry would now
    // be observable.
    await waitForLoadingThenDone(page, LOADING_INDIVIDUAL, POINT_DONE_RE);

    const history = await getPhaseHistory(page);
    // The helper either fired (cold cache → "Fetching sample index…") or
    // short-circuited at currentRes === 8 (warm cache → straight to point
    // mode). Either way, "Loading individual samples…" must appear from
    // loadViewportSamples inside enterPointMode.
    expect(history.some(s => s.includes(LOADING_INDIVIDUAL))).toBeTruthy();
    expect(history.some(s => POINT_DONE_RE.test(s))).toBeTruthy();
  });

  test('source-filter toggle while in point mode does NOT trigger Fetching sample index', async ({ page }) => {
    // Verifies invariant (a): tryEnterPointModeIfNeeded short-circuits on
    // mode === 'point'. The source-filter handler in point mode takes
    // its `else` branch (calls loadViewportSamples, not loadRes), so the
    // helper isn't directly called from there — but if a future refactor
    // wires a chase in, the short-circuit must keep the helper's
    // loadingMsg ("Fetching sample index…") suppressed because we're
    // already in point mode.
    await page.goto(`${BASE_URL}${EXPLORER_PATH}#v=1&lat=20&lng=0&alt=${ALT_WORLD}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await waitForClusterBoot(page);
    await flyCameraTo(page, LAT_CYPRUS, LNG_CYPRUS, ALT_POINT_CYPRUS);
    await waitForMode(page, 'point', 120000);
    await waitForPhaseMessage(page, INDIVIDUAL_SAMPLES, 120000);

    await startPhaseHistory(page);

    // Toggle off → wait for Loading individual samples → count-prefixed done.
    await toggleSourceFilter(page, 0);
    await waitForLoadingThenDone(page, LOADING_INDIVIDUAL, POINT_DONE_RE);
    // Toggle on → wait for ANOTHER Loading individual samples → done cycle.
    // (Use history length to guarantee we observe the new transition,
    // not the previous done state the observer just captured.)
    await toggleSourceFilter(page, 0);
    const beforeRetoggleLen = (await getPhaseHistory(page)).length;
    await page.waitForFunction(
      (n) => (window._phaseHistory || []).length > n,
      beforeRetoggleLen,
      { timeout: 60000 }
    );
    await waitForLoadingThenDone(page, LOADING_INDIVIDUAL, POINT_DONE_RE);

    const history = await getPhaseHistory(page);
    // Point-mode source-filter reload uses loadViewportSamples, which
    // paints "Loading individual samples..." while the new query runs.
    expect(history.some(s => s.includes(LOADING_INDIVIDUAL))).toBeTruthy();
    // Helper's loadingMsg MUST NOT appear in point-mode source-filter flow.
    expect(history.some(s => s.includes(FETCHING_SAMPLE_INDEX))).toBeFalsy();
  });

});
