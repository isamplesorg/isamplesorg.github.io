// Unit tests for assets/js/explorer-utils.js (issue #249, PR3).
// Run: node --test tests/unit/   (Node built-ins only, no install)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    escapeHtml, searchTerms, parseNum, csvParamValues, sourceUrl, readHash,
    facetCountsDisplayState, formatPlaceName, panelWriteAllowed,
} from '../../assets/js/explorer-utils.js';

test('escapeHtml escapes the five HTML-significant chars; nullish -> ""', () => {
    assert.equal(
        escapeHtml(`<a href="x">O'B & C</a>`),
        '&lt;a href=&quot;x&quot;&gt;O&#39;B &amp; C&lt;/a&gt;'
    );
    assert.equal(escapeHtml(null), '');
    assert.equal(escapeHtml(undefined), '');
    assert.equal(escapeHtml(0), '0');
});

test('formatPlaceName: array -> joined string; null/empty -> ""', () => {
    assert.equal(formatPlaceName(['Country', 'Region', 'Site']), 'Country › Region › Site');
    assert.equal(formatPlaceName(['Only']), 'Only');
    assert.equal(formatPlaceName([]), '');
    assert.equal(formatPlaceName(null), '');
    assert.equal(formatPlaceName(undefined), '');
    assert.equal(formatPlaceName(['A', null, 'B']), 'A › B');  // filter(Boolean) drops null entries
});

test('formatPlaceName: works on a non-Array iterable (Arrow Vector shape) — #311', () => {
    // Reproduces the actual bug: DuckDB-WASM/Arrow LIST columns come back as
    // an iterable, .length-bearing object that is NOT a plain JS Array —
    // Array.isArray() on this returns false, which is exactly what silently
    // blanked every Place cell once place_name started carrying real data.
    class FakeArrowVector {
        constructor(items) { this._items = items; this.length = items.length; }
        [Symbol.iterator]() { return this._items[Symbol.iterator](); }
    }
    const vector = new FakeArrowVector(['Axial Seamount summit caldera']);
    assert.equal(Array.isArray(vector), false, 'sanity: the fake vector must NOT be a plain Array');
    assert.equal(formatPlaceName(vector), 'Axial Seamount summit caldera');
});

test('searchTerms splits on whitespace, drops empties', () => {
    assert.deepEqual(searchTerms('  hello   world '), ['hello', 'world']);
    assert.deepEqual(searchTerms(''), []);
    assert.deepEqual(searchTerms(null), []);
    assert.deepEqual(searchTerms('one'), ['one']);
});

test('parseNum: default for nullish/non-finite, clamps to [min,max]', () => {
    assert.equal(parseNum(null, 5), 5);
    assert.equal(parseNum(undefined, 7), 7);
    assert.equal(parseNum('abc', 5), 5);
    assert.equal(parseNum('45', 0, 0, 90), 45);
    assert.equal(parseNum('100', 0, 0, 90), 90);   // clamp max
    assert.equal(parseNum('-5', 0, 0, 90), 0);     // clamp min
    assert.equal(parseNum('3.5', 0), 3.5);
});

test('csvParamValues: null when absent, [] when empty, trimmed non-empty list', () => {
    assert.equal(csvParamValues(new URLSearchParams(''), 'x'), null);
    assert.deepEqual(csvParamValues(new URLSearchParams('x='), 'x'), []);
    assert.deepEqual(csvParamValues(new URLSearchParams('x=a,b, c ,'), 'x'), ['a', 'b', 'c']);
});

test('sourceUrl: n2t.net resolver; null for falsy', () => {
    assert.equal(sourceUrl('ark:/28722/k2x'), 'https://n2t.net/ark:/28722/k2x');
    assert.equal(sourceUrl('IGSN:ABC123'), 'https://n2t.net/IGSN:ABC123');
    assert.equal(sourceUrl(''), null);
    assert.equal(sourceUrl(null), null);
});

test('readHash: full round-trip parse', () => {
    assert.deepEqual(
        readHash('#v=1&lat=10&lng=20&alt=500&heading=45&pitch=-30&mode=point&pid=abc&h3=8a&heatmap=1'),
        { v: 1, lat: 10, lng: 20, alt: 500, heading: 45, pitch: -30, mode: 'point', pid: 'abc', h3: '8a', heatmap: true }
    );
});

test('readHash: empty hash -> defaults', () => {
    assert.deepEqual(
        readHash(''),
        { v: 0, lat: null, lng: null, alt: null, heading: 0, pitch: -90, mode: null, pid: null, h3: null, heatmap: false }
    );
});

test('readHash: clamps lat/lng/alt and treats heatmap!=1 as false', () => {
    const h = readHash('#lat=999&lng=-999&alt=50&heatmap=0');
    assert.equal(h.lat, 90);      // clamp to +90
    assert.equal(h.lng, -180);    // clamp to -180
    assert.equal(h.alt, 100);     // clamp to min 100
    assert.equal(h.heading, 0);   // default
    assert.equal(h.heatmap, false);
});

// #313 P0: pending -> "Loading…", ready/failed (when reached at all) -> dash.
// In practice the caller never reaches this decision with status === 'ready'
// (applyMaskIndexCounts only returns 'fallthrough'/'unavailable' when the
// index ISN'T ready), but the function still resolves a definite state for
// every input so the UI logic stays a total function.
test('facetCountsDisplayState: index still loading -> pending (Loading…, not the dash)', () => {
    assert.equal(facetCountsDisplayState('pending', 'fallthrough'), 'pending');
});

test('facetCountsDisplayState: index load failed -> unavailable (dash + tooltip)', () => {
    assert.equal(facetCountsDisplayState('failed', 'fallthrough'), 'unavailable');
});

test('facetCountsDisplayState: index ready but the count QUERY itself failed -> unavailable', () => {
    assert.equal(facetCountsDisplayState('ready', 'unavailable'), 'unavailable');
    assert.equal(facetCountsDisplayState('pending', 'unavailable'), 'unavailable');
    assert.equal(facetCountsDisplayState('failed', 'unavailable'), 'unavailable');
});

test('facetCountsDisplayState: ready + fallthrough is not a state the caller produces, but resolves safely', () => {
    assert.equal(facetCountsDisplayState('ready', 'fallthrough'), 'unavailable');
});

test('panelWriteAllowed: a producer may write only while it holds the latest panel generation (#172 Inc 1)', () => {
    // A captured generation equal to the current one → this producer still owns
    // the #samplesSection list and may write list + pins.
    assert.equal(panelWriteAllowed(1, 1), true);
    assert.equal(panelWriteAllowed(7, 7), true);
    // A newer producer has since bumped viewer._panelGen → the older producer's
    // captured generation is stale and it must bail (closes the search-vs-cluster
    // race in BOTH orders: whoever started last holds the highest generation).
    assert.equal(panelWriteAllowed(1, 2), false);
    assert.equal(panelWriteAllowed(2, 1), false);
    // Strict identity — no coercion surprises.
    assert.equal(panelWriteAllowed(0, 0), true);
});
