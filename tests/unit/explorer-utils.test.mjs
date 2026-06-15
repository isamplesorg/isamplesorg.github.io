// Unit tests for assets/js/explorer-utils.js (issue #249, PR3).
// Run: node --test tests/unit/   (Node built-ins only, no install)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    escapeHtml, searchTerms, parseNum, csvParamValues, sourceUrl, readHash,
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
