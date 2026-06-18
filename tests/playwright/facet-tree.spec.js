/**
 * #281/#282 Half(b) increment 1 — Material facet hierarchy (preview flag).
 *
 * Verifies the `?facets=tree` preview: flag OFF leaves Material flat (unchanged);
 * flag ON renders the expandable tree and selecting a node filters the table to
 * that node's whole SUBTREE via the membership table (no client-side expansion).
 *
 * GATED: needs the hierarchy data (facet_tree_summaries / sample_facet_membership /
 * vocab_labels-with-broader). Until those are published to R2, run against the local
 * docs/data mirror:
 *   FACET_TREE_LOCAL=1 TEST_URL=http://localhost:5860 npx playwright test facet-tree
 * (the spec drives ?data_base=/data). Skipped by default so CI stays green until the
 * R2 publish; flip the skip / drop ?data_base once the files are remote.
 */
const { test, expect } = require('@playwright/test');

const LOCAL = !!process.env.FACET_TREE_LOCAL;
const DATA = LOCAL ? '&data_base=/data' : '';
// Clearly-global altitude (> isGlobalView's 1e7 threshold) so Material counts take
// the fast baseline path (live membership counts are reserved for zoomed views).
const WORLD = '#v=1&lat=20&lng=0&alt=15000000';

test.describe('Material facet tree (#281/#282 preview)', () => {
  test.skip(!LOCAL, 'needs hierarchy data — run with FACET_TREE_LOCAL=1 against the docs/data mirror until R2 publish');
  test.setTimeout(150000);

  test('flag OFF → Material stays a flat list (no tree nodes)', async ({ page }) => {
    await page.goto(`/explorer.html?facets=flat${DATA}${WORLD}`);
    await page.waitForFunction(
      () => document.querySelectorAll('#materialFilterBody .facet-row[data-facet="material"]').length > 0,
      null, { timeout: 90000 });
    const treenodes = await page.evaluate(() => document.querySelectorAll('#materialFilterBody .facet-treenode').length);
    expect(treenodes).toBe(0);
  });

  test('flag ON → tree renders; selecting a parent filters the table to its subtree', async ({ page }) => {
    await page.goto(`/explorer.html?facets=tree${DATA}${WORLD}`);
    await page.waitForFunction(
      () => document.querySelectorAll('#materialFilterBody .facet-treenode').length > 0,
      null, { timeout: 90000 });

    // Tree structure: a non-selectable root group, several nodes, carets, and the
    // deepest level collapsed (first two levels unfolded, #281).
    const info = await page.evaluate(() => ({
      nodes: document.querySelectorAll('#materialFilterBody .facet-treenode').length,
      hasRoot: !!document.querySelector('#materialFilterBody .facet-treeroot'),
      carets: document.querySelectorAll('#materialFilterBody .facet-caret').length,
      collapsed: document.querySelectorAll('#materialFilterBody .facet-children.collapsed').length,
      earthmaterial: !!document.querySelector('#materialFilterBody input[value*="/earthmaterial"]'),
    }));
    expect(info.nodes).toBeGreaterThan(5);
    expect(info.hasRoot).toBe(true);
    expect(info.carets).toBeGreaterThan(0);
    expect(info.collapsed).toBeGreaterThan(0);
    expect(info.earthmaterial).toBe(true);

    // Selecting the "earthmaterial" parent must filter the table to its whole
    // subtree (membership encodes ancestors → no client expansion needed).
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[value*="/earthmaterial"]');
      cb.checked = true;
      document.getElementById('materialFilterBody').dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.waitForFunction(
      () => /of [\d,]+\)/.test(document.getElementById('tablePageInfo')?.textContent || ''),
      null, { timeout: 60000 });
    const total = await page.evaluate(() => {
      const m = (document.getElementById('tablePageInfo')?.textContent || '').match(/of ([\d,]+)\)/);
      return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
    });
    expect(total).toBeGreaterThan(0);
  });

  // Known 202608 subtree/union totals — deterministic for this dataset, so polling
  // to the exact value also guarantees the filter has applied (no stale-pager read).
  const EARTHMATERIAL_TOTAL = 4091133;        // earthmaterial subtree
  const MINERAL_OR_SOIL_TOTAL = 333253;       // mineral ∪ soil (peers)

  test('polish: checking a parent inherits its children (checked+disabled); peers go OR with an indeterminate parent', async ({ page }) => {
    const toggle = (sub, val) => page.evaluate(({ sub, val }) => {
      const cb = document.querySelector(`#materialFilterBody input[value*="${sub}"]`);
      cb.checked = val; cb.dispatchEvent(new Event('change', { bubbles: true }));
    }, { sub, val });
    const total = async () => page.evaluate(() => {
      const m = (document.getElementById('tablePageInfo')?.textContent || '').match(/of ([\d,]+)\)/);
      return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
    });
    await page.goto(`/explorer.html?facets=tree${DATA}${WORLD}`);
    await page.waitForFunction(
      () => document.querySelectorAll('#materialFilterBody .facet-treenode').length > 0,
      null, { timeout: 90000 });

    // Check the "earthmaterial" parent → a child ("mineral") becomes inherited
    // (checked + disabled), and the table filters to the whole subtree.
    await toggle('/earthmaterial', true);
    const child = await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[value*="/mineral"]');
      return { checked: cb.checked, disabled: cb.disabled };
    });
    expect(child).toEqual({ checked: true, disabled: true });
    await expect.poll(total, { timeout: 60000, intervals: [500, 1000, 2000] }).toBe(EARTHMATERIAL_TOTAL);

    // Uncheck the parent; check two PEERS (mineral + soil) → the parent shows the
    // indeterminate "–" state, and the table is their OR/union (smaller than the parent).
    await toggle('/earthmaterial', false);
    await toggle('/mineral', true);
    await toggle('/soil', true);
    const parentState = await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[value*="/earthmaterial"]');
      return { checked: cb.checked, indeterminate: cb.indeterminate };
    });
    expect(parentState).toEqual({ checked: false, indeterminate: true });
    await expect.poll(total, { timeout: 60000, intervals: [500, 1000, 2000] }).toBe(MINERAL_OR_SOIL_TOTAL);
    expect(MINERAL_OR_SOIL_TOTAL).toBeLessThan(EARTHMATERIAL_TOTAL);
  });

  test('URL round-trip: a parent selection serializes the minimal node and restores inherited state', async ({ page }) => {
    const EARTHMATERIAL = 'https://w3id.org/isample/vocabulary/material/1.0/earthmaterial';
    // Select earthmaterial, then assert the URL carries ONLY that node (minimal — no
    // expanded descendants like /mineral).
    await page.goto(`/explorer.html?facets=tree${DATA}${WORLD}`);
    await page.waitForFunction(() => document.querySelectorAll('#materialFilterBody .facet-treenode').length > 0, null, { timeout: 90000 });
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[value*="/earthmaterial"]');
      cb.checked = true; cb.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await expect.poll(async () => {
      const p = new URLSearchParams(new URL(await page.evaluate(() => location.href)).search);
      return p.get('material');
    }, { timeout: 30000, intervals: [250, 500, 1000] }).toBe(EARTHMATERIAL);
    const url = await page.evaluate(() => location.href);
    expect(url).not.toContain('mineral');  // descendants are NOT expanded into the URL

    // Reload that URL fresh → earthmaterial restored as selected, and a child shows
    // the inherited (checked + disabled) state.
    await page.goto(url.includes('data_base') ? url : `${url}${DATA.replace('&', url.includes('?') ? '&' : '?')}`);
    await page.waitForFunction(() => document.querySelectorAll('#materialFilterBody .facet-treenode').length > 0, null, { timeout: 90000 });
    const restored = await page.evaluate(() => {
      const par = document.querySelector('#materialFilterBody input[value*="/earthmaterial"]');
      const kid = document.querySelector('#materialFilterBody input[value*="/mineral"]');
      return { parentChecked: par.checked, kidChecked: kid.checked, kidDisabled: kid.disabled };
    });
    expect(restored).toEqual({ parentChecked: true, kidChecked: true, kidDisabled: true });
  });

  // #290: live viewport / cross-filtered Material tree counts (from membership).
  const legendCount = (page, sub) => page.evaluate((s) => {
    const sp = document.querySelector(`#materialFilterBody .facet-count[data-value*="${s}"]`);
    const m = (sp?.textContent || '').match(/([\d,]+)/);
    return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
  }, sub);
  const tableTotal = (page) => page.evaluate(() => {
    const m = (document.getElementById('tablePageInfo')?.textContent || '').match(/of ([\d,]+)\)/);
    return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
  });

  test('live counts: tree node counts shrink to the viewport (not static baseline)', async ({ page }) => {
    test.setTimeout(180000);
    // Global view → baseline (global tree counts).
    await page.goto(`/explorer.html?facets=tree${DATA}#v=1&lat=0&lng=0&alt=15000000`);
    await page.waitForFunction(() => document.querySelectorAll('#materialFilterBody .facet-treenode').length > 0, null, { timeout: 90000 });
    await page.waitForTimeout(2500);
    const globalEarth = await legendCount(page, '/earthmaterial');
    expect(globalEarth).toBeGreaterThan(1000000);
    // Zoom to a small region → the same node's count must drop (viewport-scoped).
    await page.evaluate(async () => {
      const v = await window._ojs.ojsConnector.mainModule.value('viewer');
      v.scene.requestRenderMode = false;
      v.camera.flyTo({ destination: window.Cesium.Cartesian3.fromDegrees(33, 35, 400000), duration: 0 });
    });
    await page.waitForTimeout(4000);
    const zoomedEarth = await legendCount(page, '/earthmaterial');
    expect(zoomedEarth).toBeLessThan(globalEarth);
    expect(zoomedEarth).toBeGreaterThanOrEqual(0);
  });

  test('live counts coherence: legend(node) == table when that node is the filter (#245), parent >= child', async ({ page }) => {
    test.setTimeout(180000);
    await page.goto(`/explorer.html?facets=tree${DATA}#v=1&lat=35&lng=33&alt=500000`);
    await page.waitForFunction(() => document.querySelectorAll('#materialFilterBody .facet-treenode').length > 0, null, { timeout: 90000 });
    await page.waitForTimeout(3500);
    const legEarth = await legendCount(page, '/earthmaterial');
    const legRock = await legendCount(page, '/rock');
    expect(legEarth).toBeGreaterThanOrEqual(legRock);  // parent >= child, in-viewport
    expect(legEarth).toBeGreaterThan(0);
    // Selecting earthmaterial filters the table to exactly its viewport legend count.
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[value*="/earthmaterial"]');
      cb.checked = true; cb.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await expect.poll(() => tableTotal(page), { timeout: 60000, intervals: [500, 1000, 2000] }).toBe(legEarth);
  });

  test('live counts cross-filter both ways (zoomed): a source narrows Material; Material narrows sources', async ({ page }) => {
    test.setTimeout(180000);
    const sumCounts = (page, container) => page.evaluate((c) => {
      let s = 0;
      document.querySelectorAll(`#${c} .facet-count`).forEach(el => {
        const m = (el.textContent || '').match(/([\d,]+)/);
        if (m) s += parseInt(m[1].replace(/,/g, ''), 10);
      });
      return s;
    }, container);
    await page.goto(`/explorer.html?facets=tree${DATA}#v=1&lat=35&lng=33&alt=500000`);
    await page.waitForFunction(() => document.querySelectorAll('#materialFilterBody .facet-treenode').length > 0, null, { timeout: 90000 });
    await page.waitForTimeout(3500);
    const matEarth0 = await legendCount(page, '/earthmaterial');
    expect(matEarth0).toBeGreaterThan(0);

    // (a) source → material: unchecking a source must not INCREASE a material count.
    await page.evaluate(() => {
      const cb = document.querySelector('#sourceFilter input[type="checkbox"]:checked');
      if (cb) { cb.checked = false; cb.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await page.waitForTimeout(3000);
    const matEarth1 = await legendCount(page, '/earthmaterial');
    expect(matEarth1).toBeLessThanOrEqual(matEarth0);

    // restore source, then (b) material → source: selecting a Material node must not
    // INCREASE the source-count total (it scopes sources to that subtree).
    await page.evaluate(() => {
      const cb = document.querySelector('#sourceFilter input[type="checkbox"]:not(:checked)');
      if (cb) { cb.checked = true; cb.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await page.waitForTimeout(3000);
    const srcSum0 = await sumCounts(page, 'sourceFilter');
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[value*="/earthmaterial"]');
      cb.checked = true; cb.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.waitForTimeout(3000);
    const srcSum1 = await sumCounts(page, 'sourceFilter');
    expect(srcSum1).toBeLessThanOrEqual(srcSum0);
    expect(srcSum1).toBeGreaterThan(0);
  });

  test('graceful fallback: if the tree data 404s, Material renders flat and still filters', async ({ page }) => {
    // Deploy-safety (Codex r2/r3): with ?facets=tree but the hierarchy files
    // missing, renderMaterialTreeFacet() catches and renders the flat list, and
    // materialTreeActive() is false everywhere → selection/filtering use the flat
    // facets_v3 path (NOT the missing membership file).
    await page.route('**/*facet_tree_summaries*', route => route.fulfill({ status: 404, body: '' }));
    await page.goto(`/explorer.html?facets=tree${DATA}${WORLD}`);
    await page.waitForFunction(
      () => document.querySelectorAll('#materialFilterBody .facet-row[data-facet="material"]').length > 0,
      null, { timeout: 90000 });
    const treenodes = await page.evaluate(() => document.querySelectorAll('#materialFilterBody .facet-treenode').length);
    expect(treenodes).toBe(0);  // fell back to flat
    // a flat material selection still filters the table (uses facets_v3, no membership)
    await page.evaluate(() => {
      const cb = document.querySelector('#materialFilterBody input[type="checkbox"]');
      cb.checked = true; cb.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.waitForFunction(() => /of [\d,]+\)/.test(document.getElementById('tablePageInfo')?.textContent || ''), null, { timeout: 60000 });
    const total = await page.evaluate(() => {
      const m = (document.getElementById('tablePageInfo')?.textContent || '').match(/of ([\d,]+)\)/);
      return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
    });
    expect(total).toBeGreaterThan(0);
  });
});
