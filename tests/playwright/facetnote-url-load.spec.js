/**
 * #facetNote visibility on URL deep-link (issue #234, roadmap step 1).
 *
 * Regression: opening the explorer with `?material=…` (or `context=` /
 * `object_type=`) restored checkbox state via `applyQueryToFacetFilters`
 * but did NOT fire the `change` event, so the cluster-mode honesty note
 * (`#facetNote`) stayed hidden even though the filter was active. A user
 * arriving via a shared URL would see the dimmed-cluster-dots behavior
 * with no explanation.
 *
 * The fix introduces `syncFacetNote()` as the single source of truth for
 * the visibility invariant
 *     visible ⇔ (any facet active) ∧ (mode === 'cluster')
 * and calls it from the four state-mutation sites (URL-load, change
 * handler, enterPointMode, exitPointMode).
 *
 * This spec covers the URL-load path; the mode-transition behavior is
 * exercised indirectly by `url-roundtrip.spec.js` (which already drives
 * point-mode deep-links — they must not surface the note).
 */

const { test, expect } = require('@playwright/test');
const { explorerUrl } = require('./helpers/url');

// Cluster-altitude default (well above ENTER_POINT_ALT = 120000).
const ALT_CLUSTER = 5000000;
const LAT = 0;
const LNG = 0;

/** Wait until the facetFilters cell has populated material checkboxes.
 *  The cell waits for `phase1`, then queries `facet_summaries.parquet`
 *  remote; first paint can take a few seconds against a cold cache. */
async function waitForFacetCheckboxes(page, timeoutMs = 60000) {
  await page.waitForFunction(
    () => document.querySelectorAll('#materialFilterBody input[type="checkbox"]').length > 0,
    null,
    { timeout: timeoutMs }
  );
}

/** Wait until `viewer._globeState.mode` equals `expected`. */
async function waitForMode(page, expected, timeoutMs = 60000) {
  await page.waitForFunction(
    async (mode) => {
      try {
        const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
        return v?._globeState?.mode === mode;
      } catch { return false; }
    },
    expected,
    { timeout: timeoutMs }
  );
}

test.describe('#facetNote URL deep-link visibility (issue #234 step 1)', () => {
  test.setTimeout(120000);

  test('cluster mode + ?material= → #facetNote visible', async ({ page }) => {
    // Boot the page once to discover a real material URI from the rendered
    // checkboxes. Hardcoding a URI would couple the test to a specific
    // vocabulary version; reading the live data keeps it self-healing.
    await page.goto(explorerUrl(`#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_CLUSTER}`));
    await waitForMode(page, 'cluster');
    await waitForFacetCheckboxes(page);

    const materialUri = await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[type="checkbox"]');
      return cb ? cb.value : null;
    });
    expect(materialUri).toBeTruthy();

    // Now reload with the chosen material in the query string. This is the
    // path that was broken: applyQueryToFacetFilters() ticks the box but
    // syncFacetNote() must run to flip #facetNote visible.
    const encoded = encodeURIComponent(materialUri);
    await page.goto(
      explorerUrl(`?material=${encoded}#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_CLUSTER}`)
    );
    await waitForMode(page, 'cluster');
    await waitForFacetCheckboxes(page);

    // Wait for the checkbox to be in the restored-checked state. The
    // facetFilters cell calls applyQueryToFacetFilters() immediately after
    // renderFilter, but the test polls to be robust against ordering.
    await page.waitForFunction(
      (uri) => {
        const cb = document.querySelector(
          `#materialFilterBody input[type="checkbox"][value="${CSS.escape(uri)}"]`
        );
        return cb?.checked === true;
      },
      materialUri,
      { timeout: 30000 }
    );

    const noteState = await page.evaluate(() => {
      const el = document.getElementById('facetNote');
      if (!el) return { exists: false };
      const styleDisplay = el.style.display;
      const computed = window.getComputedStyle(el).display;
      return { exists: true, styleDisplay, computed };
    });

    expect(noteState.exists).toBe(true);
    // The fix sets style.display to 'block' for the (active && cluster) case.
    expect(noteState.styleDisplay).toBe('block');
    expect(noteState.computed).not.toBe('none');
  });

  test('cluster mode + no facet params → #facetNote hidden', async ({ page }) => {
    // Negative control: arriving with no facet params must keep the note
    // hidden. Guards against an over-eager `syncFacetNote()` that flips
    // visibility independent of `hasFacetFilters()`.
    await page.goto(explorerUrl(`#v=1&lat=${LAT}&lng=${LNG}&alt=${ALT_CLUSTER}`));
    await waitForMode(page, 'cluster');
    await waitForFacetCheckboxes(page);

    const noteState = await page.evaluate(() => {
      const el = document.getElementById('facetNote');
      return { exists: !!el, display: el?.style.display };
    });
    expect(noteState.exists).toBe(true);
    expect(noteState.display).toBe('none');
  });
});
