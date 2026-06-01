const { test, expect } = require('@playwright/test');
const { explorerUrl } = require('./helpers/url');

const TERM = 'bucchero';
const VIEW_HASH = '#v=1&lat=42.5&lng=12.0&alt=400000';
const DATA_DEBUG = '?data_base=/data&debug=a1';
const AREA_DATA_DEBUG = '?data_base=/data&debug=a1&search_scope=area';

const EARTH_MATERIAL = 'https://w3id.org/isample/vocabulary/material/1.0/earthmaterial';
const OTHER_SOLID_OBJECT = 'https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/othersolidobject';

async function waitForFacetUI(page) {
    await page.waitForFunction(
        () => document.querySelectorAll('#sourceFilter .facet-count[data-facet="source"]').length > 0
           && document.querySelectorAll('#materialFilterBody .facet-count[data-facet="material"]').length > 0
           && document.querySelectorAll('#objectTypeFilterBody .facet-count[data-facet="object_type"]').length > 0,
        null,
        { timeout: 120000 }
    );
}

async function submitSearchAndWaitForSettle(page, term = TERM) {
    await page.fill('#sampleSearch', term);
    await page.press('#sampleSearch', 'Enter');

    await page.waitForFunction(
        (t) => window.__searchFilter?.active === true
            && window.__searchFilter?.term === t
            && window.__searchFilter?.total > 0,
        term,
        { timeout: 120000 }
    );

    await page.waitForFunction(
        () => !document.body.classList.contains('explorer-busy')
            && /matches in this map view/.test(document.getElementById('tableMeta')?.textContent || ''),
        null,
        { timeout: 120000 }
    );

    await expect.poll(async () => {
        return page.evaluate(() => document.querySelectorAll('.facet-count.recomputing').length);
    }, { timeout: 60000, intervals: [250, 500, 1000] }).toBe(0);
}

async function readFacetCount(page, facet, value) {
    const text = await page.locator(`.facet-count[data-facet="${facet}"][data-value="${value}"]`).first().textContent();
    const match = (text || '').match(/\(([\d,]+)\)/);
    return match ? Number(match[1].replace(/,/g, '')) : NaN;
}

async function expectBuccheroFacetCounts(page) {
    await expect.poll(
        () => readFacetCount(page, 'source', 'SESAR'),
        { timeout: 60000, intervals: [250, 500, 1000] }
    ).toBe(0);

    await expect.poll(
        () => readFacetCount(page, 'source', 'OPENCONTEXT'),
        { timeout: 60000, intervals: [250, 500, 1000] }
    ).toBeGreaterThan(0);

    await expect.poll(
        () => readFacetCount(page, 'object_type', OTHER_SOLID_OBJECT),
        { timeout: 60000, intervals: [250, 500, 1000] }
    ).toBe(0);

    await expect.poll(
        () => readFacetCount(page, 'material', EARTH_MATERIAL),
        { timeout: 60000, intervals: [250, 500, 1000] }
    ).toBe(0);
}

test.describe('A1 search-aware facet counts after world-search flyTo (#253)', () => {
    test.setTimeout(240000);

    test('area-scope diagnostic and world-scope committed search both leave legend search-filtered', async ({ page }) => {
        // Diagnostic: area-scope search does not auto-fly the camera. If this
        // path is correct but world scope is not, the culprit is sequencing,
        // not a missing search predicate in updateCrossFilteredCounts().
        await page.goto(explorerUrl(`${AREA_DATA_DEBUG}${VIEW_HASH}`));
        await waitForFacetUI(page);
        await submitSearchAndWaitForSettle(page);
        await expectBuccheroFacetCounts(page);

        // Regression path: world-scope search auto-flies to result[0]. The
        // legend must still end on a final, search-aware count refresh without
        // expanding any facet section.
        await page.goto(explorerUrl(`${DATA_DEBUG}${VIEW_HASH}`));
        await waitForFacetUI(page);
        await submitSearchAndWaitForSettle(page);
        await expectBuccheroFacetCounts(page);
    });
});
