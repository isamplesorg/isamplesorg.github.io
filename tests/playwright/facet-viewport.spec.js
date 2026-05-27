/**
 * B1 viewport-aware facet counts (issue #234, roadmap step 3).
 *
 * Behavior change: the facet-legend counts (per-source, per-material,
 * per-context, per-object_type) now reflect only the samples currently
 * visible on the map, not the global dataset. Pan or zoom → counts
 * recompute. The `.recomputing` italic state appears synchronously on
 * `camera.moveStart` and clears once the post-moveEnd debounced query
 * lands and `applyFacetCounts` writes the new values.
 *
 * Implementation summary (see explorer.qmd):
 *   - `isGlobalView()` returns true when the camera shows ≈the whole
 *     world (or is off-globe). Used to gate the cube fast-path off and
 *     decide whether to JOIN to `lite_url` for a bbox-scoped query.
 *   - `viewer.camera.moveStart` → `markFacetCountsRecomputing()` (sync).
 *   - `viewer.camera.moveEnd` → `refreshFacetCounts()` (debounced 250ms,
 *     stale-guarded by `facetCountsReqId`).
 *   - `updateCrossFilteredCounts` snapshots bboxSQL once at function
 *     entry; cube fast-path skipped when bboxSQL is set; slow path
 *     JOINs facets_url f ↔ lite_url l ON l.pid = f.pid with the bbox
 *     predicate on (l.latitude, l.longitude).
 *
 * What this spec covers:
 *   - Global-view boot → counts populated, no `.recomputing` left over.
 *   - flyTo small viewport (Cyprus) → `.recomputing` appears, counts
 *     shrink relative to global, `.recomputing` clears.
 *   - flyTo back to global → counts restore to (within 1% of) original.
 *   - moveStart marks `.recomputing` synchronously, before any 250ms
 *     debounce can have run.
 *
 * What this spec does NOT cover:
 *   - Cancellation race when two pans land back-to-back inside the
 *     250ms debounce window — covered by the `facetCountsReqId` stale
 *     guard in the implementation; a reliable Playwright race here
 *     would require monkey-patching `db.query` to inject latency and
 *     was deferred to a follow-up if Codex flags it as missing.
 *   - JOIN performance under stress (the Q1(a) decision was to accept
 *     the JOIN cost for this PR and bake a combined parquet only if
 *     real-world latency proves bad). The local-validation step in
 *     the implementation plan logs query latency for visibility.
 */
const { test, expect } = require('@playwright/test');

const EXPLORER_PATH = '/explorer.html';

// Global view position. alt=15000000 (15,000 km) is above the
// `GLOBAL_VIEW_ALT_M = 1e7` shortcut in `isGlobalView()`, so the
// implementation will treat this as the no-bbox baseline path
// regardless of any per-angle quirks in `computeViewRectangle`.
// Without the altitude shortcut, at lower altitudes (e.g. 5000 km)
// Cesium reports an ≈hemispheric bounding rect over the equator and
// `isGlobalView()` would return false — which would conflate the
// boot-time bbox query with the "true global" baseline read.
const GLOBAL_HASH = '#v=1&lat=0&lng=0&alt=15000000';

// Cyprus-centered small viewport (~35°N, 33°E, alt 500km). Cyprus has
// archaeology data in iSamples (PKAP, OpenContext) and is small enough
// that the bbox-scoped count must drop substantially below global.
const CYPRUS_LAT = 35;
const CYPRUS_LNG = 33;
const CYPRUS_ALT = 500000;

/** Wait until facet UI hydrates: at least one `.facet-count[data-facet="source"]`
 *  span is in the DOM. The facetFilters cell renders these after
 *  facet_summaries.parquet loads, which is the same precondition existing
 *  tests (facetnote-url-load) wait for. */
async function waitForFacetUI(page, ms = 60000) {
    await page.waitForFunction(
        () => document.querySelectorAll('.facet-count[data-facet="source"]').length > 0,
        null, { timeout: ms }
    );
    // Also wait for materialFilterBody to populate — the existing
    // facetnote-url-load spec uses this as the "facet UI is fully wired"
    // signal, and we want to match its boot-readiness criterion.
    await page.waitForFunction(
        () => document.querySelectorAll('#materialFilterBody input[type="checkbox"]').length > 0,
        null, { timeout: ms }
    );
}

/** Wait until no `.facet-count` carries the `.recomputing` class. Catches
 *  both the cold-boot path (no recompute fires, condition true immediately)
 *  and the post-pan path (italic clears once the bbox query completes). */
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

function totalOf(counts) {
    return Object.values(counts).reduce((a, b) => a + b, 0);
}

test.describe('B1 viewport-aware facet counts (#234 step 3)', () => {
    test.setTimeout(180000);

    test('zoom in → counts shrink to viewport; zoom out → counts restore', async ({ page }) => {
        await page.goto(`${EXPLORER_PATH}${GLOBAL_HASH}`);
        await waitForFacetUI(page);
        await waitForFacetCountsStable(page);

        // Baseline at global view. Sources are stable URIs, so we can
        // compare value-by-value across the two viewport states.
        const globalCounts = await readSourceCounts(page);
        const totalGlobal = totalOf(globalCounts);
        expect(totalGlobal).toBeGreaterThan(0);

        // Fly to Cyprus.
        await flyToAndSettle(page, CYPRUS_LAT, CYPRUS_LNG, CYPRUS_ALT);

        const cyprusCounts = await readSourceCounts(page);
        const totalCyprus = totalOf(cyprusCounts);
        // Viewport-scoped total must be strictly less than global and
        // strictly greater than zero (Cyprus is known to carry data).
        expect(totalCyprus).toBeGreaterThan(0);
        expect(totalCyprus).toBeLessThan(totalGlobal);

        // No individual per-source count should exceed its global value
        // (the bbox is a subset of the world, monotonically).
        for (const [uri, n] of Object.entries(cyprusCounts)) {
            const g = globalCounts[uri] ?? 0;
            expect(n).toBeLessThanOrEqual(g);
        }

        // Fly back to the global view (alt above GLOBAL_VIEW_ALT_M).
        await flyToAndSettle(page, 0, 0, 15000000);

        const restoredCounts = await readSourceCounts(page);
        // At alt=15e6 the altitude shortcut in `isGlobalView()` forces the
        // no-bbox baseline path, so restored counts must be VALUE-BY-VALUE
        // EXACTLY equal to the first global capture — not a 1 % tolerance.
        // Codex round-1 review of PR #237 caught that a loose tolerance
        // could hide a real regression (e.g. a stale-read race writing a
        // bbox-scoped count and us mistaking it for "close enough").
        expect(restoredCounts).toEqual(globalCounts);
    });

    test('bbox-aware count under an active source filter (JOIN + filter)', async ({ page }) => {
        // The most important new SQL shape: `buildCrossFilterWhere(d.key, 'f.')`
        // emitted as `f.source IN (...)` joined to `lite_url l` for the
        // bbox predicate. This guards against column-prefix regressions
        // (e.g. dropping the `f.` qualifier → ambiguous-column error from
        // DuckDB since `lite_url` also carries a `source` column) and
        // against the JOIN inadvertently double-counting via duplicate pids.
        // Codex round-1 review of PR #237 called out the coverage gap.
        await page.goto(`${EXPLORER_PATH}${GLOBAL_HASH}`);
        await waitForFacetUI(page);
        await waitForFacetCountsStable(page);

        // Pick the source with the most data in our viewport-baseline so the
        // assertion has signal: bbox-scoped count > 0 and ≤ its global.
        const globalCounts = await readSourceCounts(page);
        const [topSource] = Object.entries(globalCounts)
            .sort((a, b) => b[1] - a[1])
            .map(([uri]) => uri);
        expect(topSource).toBeTruthy();

        // Toggle the source-checkbox state so only `topSource` remains
        // active. The sourceFilter change handler runs refreshFacetCounts;
        // at global view the cube fast-path kicks in (single value selected).
        await page.evaluate((keep) => {
            document.querySelectorAll('#sourceFilter input[type="checkbox"]').forEach(cb => {
                cb.checked = (cb.value === keep);
            });
            document.getElementById('sourceFilter').dispatchEvent(new Event('change', { bubbles: true }));
        }, topSource);
        await waitForFacetCountsStable(page);

        // Capture filtered-but-global material counts. With source filtered
        // to a single value (cube fast-path), these are the cube-derived
        // material counts under that source.
        const globalMaterialUnderFilter = await readFacetCounts(page, 'material');
        const materialsPresent = Object.values(globalMaterialUnderFilter).filter(n => n > 0).length;
        expect(materialsPresent).toBeGreaterThan(0);

        // Fly to Cyprus. The slow path now runs WITH the JOIN AND the
        // `f.source IN ('topSource')` predicate (this is the new shape
        // Codex round-1 flagged as untested). Source-dim query has WHERE
        // '1=1' (its own dim excluded) — no `f.` prefix appears — but the
        // material/context/object_type queries DO emit `f.source IN (...)`.
        await flyToAndSettle(page, CYPRUS_LAT, CYPRUS_LNG, CYPRUS_ALT);

        const cyprusSourceCounts = await readSourceCounts(page);
        // Top source must shrink from global (we're now in a small viewport)
        // but remain > 0 (Cyprus carries data for the most-represented source).
        expect(cyprusSourceCounts[topSource]).toBeGreaterThan(0);
        expect(cyprusSourceCounts[topSource]).toBeLessThanOrEqual(globalCounts[topSource]);
        for (const [uri, n] of Object.entries(cyprusSourceCounts)) {
            const g = globalCounts[uri] ?? 0;
            expect(n).toBeLessThanOrEqual(g);
        }

        // Material counts must come back from the JOIN+filter path and
        // also shrink. A silent fallback to `applyFacetCounts(key, null)`
        // (e.g. on an ambiguous-column SQL error) would write GLOBAL
        // baseline counts here — those baselines are unfiltered, so the
        // material total would actually GROW back to its global value,
        // which violates the shrink assertion below. This is the JOIN-path
        // smoke test Codex round-1 called for.
        const cyprusMaterialUnderFilter = await readFacetCounts(page, 'material');
        const filteredTotal = Object.values(globalMaterialUnderFilter).reduce((a, b) => a + b, 0);
        const cyprusTotal = Object.values(cyprusMaterialUnderFilter).reduce((a, b) => a + b, 0);
        expect(cyprusTotal).toBeGreaterThan(0);
        expect(cyprusTotal).toBeLessThan(filteredTotal);
    });

    test('moveStart marks .recomputing before the debounce can run', async ({ page }) => {
        await page.goto(`${EXPLORER_PATH}${GLOBAL_HASH}`);
        await waitForFacetUI(page);
        await waitForFacetCountsStable(page);

        // Verify the italic-stale state appears during the moveStart event
        // firing — i.e., before `refreshFacetCounts()`'s 250 ms debounce
        // can have completed. We attach our own moveStart listener AFTER
        // the explorer's; Cesium fires listeners in registration order, so
        // ours runs after the explorer's `markFacetCountsRecomputing()`
        // and observes `.recomputing` already present.
        //
        // We use `flyTo` (not `lookLeft`): Cesium only fires
        // `Camera.moveStart` on input-driven moves or programmatic flights,
        // not on direct attribute mutations like `lookLeft`/`setView`.
        // `duration > 0` is required so the flight actually animates and
        // the event sequence is moveStart → ... → moveEnd (rather than
        // collapsing to a single tick).
        const appearedAtMoveStart = await page.evaluate(async () => {
            const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
            if (!v) throw new Error('viewer not in OJS module');
            return new Promise((resolve, reject) => {
                const off = v.camera.moveStart.addEventListener(() => {
                    off();
                    resolve(document.querySelector('.facet-count.recomputing') !== null);
                });
                // Safety timeout so a regression that suppresses moveStart
                // fails the test loudly instead of hanging.
                setTimeout(() => { off(); reject(new Error('moveStart did not fire')); }, 10000);
                v.camera.flyTo({
                    destination: window.Cesium.Cartesian3.fromDegrees(30, 30, 1000000),
                    duration: 0.2,
                });
            });
        });
        expect(appearedAtMoveStart).toBe(true);

        // And it should clear after the post-moveEnd query lands.
        await waitForFacetCountsStable(page);
    });

    test('global-view boot does not leave .recomputing stuck', async ({ page }) => {
        // Negative control: a cold boot at the global view goes through the
        // baseline early-return path (no facet filter, bboxSQL===null) and
        // must NOT leave any `.recomputing` class behind. Guards against a
        // future refactor that moves `markFacetCountsRecomputing()` above
        // the early-return.
        await page.goto(`${EXPLORER_PATH}${GLOBAL_HASH}`);
        await waitForFacetUI(page);
        await waitForFacetCountsStable(page);
        const stuck = await page.evaluate(
            () => document.querySelectorAll('.facet-count.recomputing').length
        );
        expect(stuck).toBe(0);

        // Counts must be populated (baselines).
        const counts = await readSourceCounts(page);
        expect(totalOf(counts)).toBeGreaterThan(0);
    });
});
