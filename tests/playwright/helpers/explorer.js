// Explorer-specific Playwright helpers.
//
// Consolidates helpers that were copy-pasted across multiple spec files so
// `explorer-characterization.spec.js` (and future specs) can import them
// without duplicating the implementation.  Every function below is copied
// verbatim from the source spec noted in the block comment; the source spec
// keeps its own inline copy (unchanged) so existing tests remain independent.
//
// Module style follows `tests/playwright/helpers/url.js`:
//   - CommonJS (require/module.exports)
//   - No external dependencies beyond Playwright's `page` argument
//   - Each helper is exported by name
//
// Source specs:
//   explorer-map-overlay.spec.js  -> waitForBootReady
//   facet-viewport.spec.js        -> waitForFacetUI, waitForFacetCountsStable,
//                                    readFacetCounts
//   heatmap-overlay.spec.js       -> heatmapState, markerVisibility
//   url-roundtrip.spec.js         -> waitForMode, snapshot
//   search-real-count.spec.js     -> waitForSearchReady, runSearch
//
// NEW helpers (not in any existing spec):
//   getSearchFilter -> reads window.__searchFilter
//   getSelectedPid  -> reads viewer._globeState.selectedPid via OJS mainModule

// ---------------------------------------------------------------------------
// From explorer-map-overlay.spec.js
// ---------------------------------------------------------------------------

/** Wait for the OJS runtime to attach, then wait for zoomWatcher to resolve
 *  (it returns "active" once boot hydration + listener registration are
 *  complete - same pattern used in explorer-layout-stability.spec.js). */
async function waitForBootReady(page) {
  // Wait for the OJS runtime to attach, then wait for zoomWatcher to resolve
  // (it returns "active" once boot hydration + listener registration are
  // complete - same pattern used in explorer-layout-stability.spec.js).
  await page.waitForFunction(() => !!window._ojs && !!window._ojs.ojsConnector, null, { timeout: 60000 });
  await page.evaluate(async () => {
    return await window._ojs.ojsConnector.mainModule.value('zoomWatcher');
  });
}
// ---------------------------------------------------------------------------
// From facet-viewport.spec.js
// ---------------------------------------------------------------------------

/** Wait until facet UI hydrates: at least one `.facet-count[data-facet="source"]`
 *  span is in the DOM. The facetFilters cell renders these after
 *  facet_summaries.parquet loads, which is the same precondition existing
 *  tests (facetnote-url-load) wait for. */
async function waitForFacetUI(page, ms = 60000) {
    await page.waitForFunction(
        () => document.querySelectorAll('.facet-count[data-facet="source"]').length > 0,
        null, { timeout: ms }
    );
    // Also wait for materialFilterBody to populate - the existing
    // facetnote-url-load spec uses this as the "facet UI is fully wired"
    // signal, and we want to match its boot-readiness criterion.
    await page.waitForFunction(
        () => document.querySelectorAll('#materialFilterBody input[type="checkbox"]').length > 0,
        null, { timeout: ms }
    );
}

async function waitForFacetCountsStable(page, ms = 60000) {
    await page.waitForFunction(
        () => document.querySelectorAll('.facet-count.recomputing').length === 0,
        null, { timeout: ms }
    );
}

/** Read the per-value counts for a facet off the DOM. Returns `{[uri]: integer}`.
 *  Tolerates the `Number.toLocaleString()` thousands-grouping the renderer
 *  applies (en-US locale produces `1,234`; we strip commas). */
async function readFacetCounts(page, facet) {
    return page.evaluate((facet) => {
        const out = {};
        document.querySelectorAll(`.facet-count[data-facet="${facet}"]`).forEach(el => {
            const val = el.getAttribute('data-value');
            const m = (el.textContent || '').match(/\(([\d,]+)\)/);
            if (m && val) out[val] = parseInt(m[1].replace(/,/g, ''), 10);
        });
        return out;
    }, facet);
}

/** Source is the most stable facet for the unfiltered viewport-aware
 *  assertion: only a handful of values, and `_baselineCounts.source`
 *  populates at boot. */
async function readSourceCounts(page) { return readFacetCounts(page, 'source'); }

/** flyTo a destination, then wait for the post-moveEnd debounce + bbox query
 *  to settle. Uses a zero-duration flight to make the test deterministic. */
async function flyToAndSettle(page, lat, lng, alt) {
    await page.evaluate(async ({ lat, lng, alt }) => {
        const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
        if (!v) throw new Error('viewer not in OJS module');
        v.camera.flyTo({
            destination: window.Cesium.Cartesian3.fromDegrees(lng, lat, alt),
            duration: 0,
        });
    }, { lat, lng, alt });
    // Give the debounce + query a chance to land. waitForFacetCountsStable
    // is the real synchronization point; this just kicks the event loop.
    await page.waitForTimeout(50);
    await waitForFacetCountsStable(page);
}


// ---------------------------------------------------------------------------
// From heatmap-overlay.spec.js
// ---------------------------------------------------------------------------

async function heatmapState(page) {
    await page.waitForFunction(() => !!window._ojs?.ojsConnector?.mainModule, null, { timeout: 60000 });
    return await page.evaluate(() => {
      return window._ojs.ojsConnector.mainModule.value('viewer').then((v) => {
        const state = v?._heatmapOverlay || {};
        return {
          enabled: !!state.enabled,
          hasLayer: !!state.layer,
          layerShown: state.layer ? state.layer.show !== false : false,
          lastRefreshAt: state.lastRefreshAt || 0,
          lastPointCount: state.lastPointCount || 0,
          lastImageHash: state.lastImageHash || null,
          status: document.getElementById('heatmapStatus')?.textContent || '',
        };
      });
    });
  }

// Reads the live `.show` flags off the two marker collections so a test
  // can assert mutual exclusion with the heatmap overlay (#233 phase 3).
async function markerVisibility(page) {
    return await page.evaluate(() => {
      return window._ojs.ojsConnector.mainModule.value('viewer').then((v) => ({
        clusterShown: v?.h3Points?.show === true,
        pointShown: v?.samplePoints?.show === true,
        mode: v?._globeState?.mode || null,
      }));
    });
  }


// ---------------------------------------------------------------------------
// From url-roundtrip.spec.js
// ---------------------------------------------------------------------------

/** Wait until `viewer._globeState.mode` equals `expected`.
 *  Cold-cache point-mode boot can take 60–90s per #190; allow 3 minutes. */
async function waitForMode(page, expected, timeoutMs = 180000) {
  await page.waitForFunction(
    async (expectedMode) => {
      try {
        const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
        return v?._globeState?.mode === expectedMode;
      } catch { return false; }
    },
    expected,
    { timeout: timeoutMs }
  );
}

/** Wait until `loadViewportSamples` has settled into the point-mode done message.
 *  Matches on the trailing "Click one for details" phrase — it's the common
 *  denominator across both done-state phaseMsg branches at explorer.qmd:1610-1612
 *  (normal: `"<n> individual samples. Click one for details."` and cap-reached:
 *  `"<n> samples in view (showing m — zoom in for more). Click one for details."`).
 *  Codex review (PR #214 round 1) suggested switching to the count phrase
 *  `\d[\d,]*\s+individual\s+samples`, but that pattern misses the cap-reached
 *  branch which has no "individual" word, so we stay with the trailing phrase. */
async function waitForPointModeSettled(page, timeoutMs = 120000) {
  await page.waitForFunction(
    () => {
      const msg = document.getElementById('phaseMsg')?.textContent || '';
      return msg.includes('Click one for details');
    },
    null,
    { timeout: timeoutMs }
  );
}

/** Wait for boot to complete enough that the `hashchange` listener (registered
 *  late in the explorer cell at explorer.qmd:2210) is installed. `_globeState`
 *  is initialized very early (line 871), so `waitForMode` alone is not enough
 *  to guarantee the listener exists. `_suppressHashWrite` flips to false either
 *  via zoomWatcher init or at the end of the boot deep-link section (line 2734);
 *  by the time it's false, the hashchange listener is definitely registered. */
async function waitForBootSettled(page, timeoutMs = 180000) {
  await page.waitForFunction(
    async () => {
      try {
        const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
        return v?._suppressHashWrite === false;
      } catch { return false; }
    },
    null,
    { timeout: timeoutMs }
  );
}

/** Wait until the URL hash's lat/lng (and optionally alt) match the expected
 *  values within `eps` / `altEps`. Replaces fixed sleeps with a precise settle
 *  condition for moveEnd-driven hash writes (regression for #205). */
async function waitForHashLatLng(page, expectedLat, expectedLng, opts = {}) {
  const eps = opts.eps ?? 0.001;
  const expectedAlt = opts.alt ?? null;
  const altEps = opts.altEps ?? 100;
  const timeoutMs = opts.timeoutMs ?? 10000;
  await page.waitForFunction(
    ({ lat, lng, eps, alt, altEps }) => {
      const params = new URLSearchParams(location.hash.slice(1));
      const ul = parseFloat(params.get('lat'));
      const un = parseFloat(params.get('lng'));
      if (!Number.isFinite(ul) || !Number.isFinite(un)) return false;
      if (Math.abs(ul - lat) >= eps || Math.abs(un - lng) >= eps) return false;
      if (alt != null) {
        const ua = parseFloat(params.get('alt'));
        if (!Number.isFinite(ua) || Math.abs(ua - alt) >= altEps) return false;
      }
      return true;
    },
    { lat: expectedLat, lng: expectedLng, eps, alt: expectedAlt, altEps },
    { timeout: timeoutMs }
  );
}

/** Snapshot camera + mode + selection + URL hash from the live page.
 *  `selectedPid` and `selectedH3` are intentionally read from `viewer._globeState`
 *  — that's the canonical URL-selection backing state today. If a future refactor
 *  renames or relocates these fields, this spec is the place to update. */
async function snapshot(page) {
  return await page.evaluate(async () => {
    const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
    const carto = v?.camera?.positionCartographic;
    if (!carto) return null;
    return {
      url: location.href,
      hash: location.hash,
      lat: Cesium.Math.toDegrees(carto.latitude),
      lng: Cesium.Math.toDegrees(carto.longitude),
      alt: carto.height,
      mode: v._globeState.mode,
      selectedPid: v._globeState.selectedPid || null,
      selectedH3: v._globeState.selectedH3 || null,
    };
  });
}


// ---------------------------------------------------------------------------
// From search-real-count.spec.js
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// NEW helpers (not in any existing spec)
// ---------------------------------------------------------------------------

/** Read the current value of 'window.__searchFilter'.
 *  Returns the filter object '{ active, term, token, total, kind }' or null. */
async function getSearchFilter(page) {
  return page.evaluate(() => window.__searchFilter);
}

/** Read 'viewer._globeState.selectedPid' via the OJS mainModule 'viewer' value.
 *  Returns the PID string, or null if none is selected. */
async function getSelectedPid(page) {
  return page.evaluate(async () => {
    try {
      const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
      return v?._globeState?.selectedPid || null;
    } catch { return null; }
  });
}

module.exports = {
  waitForBootReady,
  waitForFacetUI,
  waitForFacetCountsStable,
  readFacetCounts,
  heatmapState,
  markerVisibility,
  waitForMode,
  snapshot,
  waitForSearchReady,
  runSearch,
  getSearchFilter,
  getSelectedPid,
};
