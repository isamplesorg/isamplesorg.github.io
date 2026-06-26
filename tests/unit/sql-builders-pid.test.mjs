// Unit tests for PID-search helpers added to assets/js/sql-builders.js
// (issues #278 search-by-PID, #26 modern-vs-classic ARK).
// Run: node --test tests/unit/   (Node built-ins only, no install)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    canonicalizePid, looksLikePid, pidSearchWhere,
} from '../../assets/js/sql-builders.js';

// ---------------------------------------------------------------------------
// canonicalizePid
// ---------------------------------------------------------------------------

test('canonicalizePid: classic ARK (ark:/) → modern form (ark:)', () => {
    assert.equal(canonicalizePid('ark:/28722/k2000027w'), 'ark:28722/k2000027w');
});

test('canonicalizePid: modern ARK already canonical — no change', () => {
    assert.equal(canonicalizePid('ark:28722/k2000027w'), 'ark:28722/k2000027w');
});

test('canonicalizePid: resolver URL stripped then ARK collapsed', () => {
    assert.equal(
        canonicalizePid('https://n2t.net/ark:/28722/k2000027w'),
        'ark:28722/k2000027w'
    );
    assert.equal(
        canonicalizePid('http://n2t.net/ark:28722/k2000027w'),
        'ark:28722/k2000027w'
    );
    // arks.org resolver
    assert.equal(
        canonicalizePid('https://arks.org/ark:/28722/k2000027w'),
        'ark:28722/k2000027w'
    );
});

test('canonicalizePid: IGSN with prefix — lowercased, otherwise unchanged', () => {
    assert.equal(canonicalizePid('IGSN:IEGIL000C'), 'igsn:iegil000c');
});

test('canonicalizePid: IGSN lowercase already', () => {
    assert.equal(canonicalizePid('igsn:iegil000c'), 'igsn:iegil000c');
});

test('canonicalizePid: bare local identifier passed through lowercased', () => {
    // No scheme prefix — just lowercase; caller handles fallback matching.
    assert.equal(canonicalizePid('IEGIL000C'), 'iegil000c');
});

test('canonicalizePid: DOI resolver URL stripped', () => {
    assert.equal(
        canonicalizePid('https://doi.org/10.5281/zenodo.123'),
        '10.5281/zenodo.123'
    );
});

test('canonicalizePid: handle.net resolver URL stripped', () => {
    assert.equal(
        canonicalizePid('https://hdl.handle.net/20.500.12535/abc'),
        '20.500.12535/abc'
    );
});

test('canonicalizePid: trims surrounding whitespace', () => {
    assert.equal(canonicalizePid('  IGSN:IEGIL000C  '), 'igsn:iegil000c');
});

// ---------------------------------------------------------------------------
// looksLikePid
// ---------------------------------------------------------------------------

test('looksLikePid: classic ARK', () => {
    assert.equal(looksLikePid('ark:/28722/k2000027w'), true);
});

test('looksLikePid: modern ARK', () => {
    assert.equal(looksLikePid('ark:28722/k2000027w'), true);
});

test('looksLikePid: IGSN with prefix', () => {
    assert.equal(looksLikePid('IGSN:IEGIL000C'), true);
    assert.equal(looksLikePid('igsn:iegil000c'), true);
});

test('looksLikePid: DOI scheme', () => {
    assert.equal(looksLikePid('doi:10.5281/zenodo.123'), true);
});

test('looksLikePid: bare DOI (starts with 10.)', () => {
    assert.equal(looksLikePid('10.5281/zenodo.123'), true);
});

test('looksLikePid: resolver URL', () => {
    assert.equal(looksLikePid('https://n2t.net/ark:/28722/k2000027w'), true);
    assert.equal(looksLikePid('https://doi.org/10.5281/zenodo.123'), true);
});

test('looksLikePid: plain text is NOT a PID', () => {
    assert.equal(looksLikePid('pottery'), false);
    assert.equal(looksLikePid('archaeological site'), false);
    assert.equal(looksLikePid('basalt'), false);
});

test('looksLikePid: bare local identifier without scheme is NOT detected', () => {
    // A bare local part like IEGIL000C has no scheme — the user must include
    // "igsn:" for the heuristic to fire. This is intentional: bare words
    // might be meaningful text and we don't want to route them via pid-search.
    assert.equal(looksLikePid('IEGIL000C'), false);
    // However, the pidSearchWhere localpart fallback still catches it when
    // the caller pairs it with a fully-prefixed term, or when the caller
    // routes it deliberately. See the integration comment in explorer.qmd.
});

// ---------------------------------------------------------------------------
// pidSearchWhere — SQL fragment shape and injection safety
// ---------------------------------------------------------------------------

test('pidSearchWhere: classic ARK produces normalised equality + localpart ILIKE', () => {
    const sql = pidSearchWhere('ark:/28722/k2000027w');
    // Stored-side normalisation:
    assert.ok(sql.includes("LOWER(REPLACE(pid, 'ark:/', 'ark:'))"), 'stored-side LOWER+REPLACE present');
    // Canonical form (ark: not ark:/) in the equality comparison:
    assert.ok(sql.includes("= 'ark:28722/k2000027w'"), 'canonical ARK in equality');
    // Localpart fallback (the part after the last '/'):
    assert.ok(sql.includes("pid ILIKE '%k2000027w%'"), 'localpart ILIKE fallback');
    // Both sides wrapped in outer parens:
    assert.ok(sql.startsWith('(') && sql.endsWith(')'), 'outer parens');
});

test('pidSearchWhere: IGSN with prefix', () => {
    const sql = pidSearchWhere('IGSN:IEGIL000C');
    assert.ok(sql.includes("= 'igsn:iegil000c'"), 'canonical IGSN equality');
    // No '/' in the IGSN value, so localpart equals the full canonical form.
    // The fallback ILIKE therefore matches the whole canonical pid substring.
    assert.ok(sql.includes("pid ILIKE '%igsn:iegil000c%'"), 'IGSN full-canonical ILIKE fallback');
});

test('pidSearchWhere: resolver URL (n2t.net) — prefix stripped in canonical', () => {
    const sql = pidSearchWhere('https://n2t.net/ark:/28722/k2000027w');
    assert.ok(sql.includes("= 'ark:28722/k2000027w'"), 'resolver prefix stripped in canonical');
    assert.ok(sql.includes("pid ILIKE '%k2000027w%'"), 'localpart fallback');
});

test('pidSearchWhere: injection-safe — single quotes escaped', () => {
    // A malicious value with a single quote must not break the SQL string.
    // canonicalizePid lowercases first, so "O'Malley" → "o'malley" → "o''malley".
    const sql = pidSearchWhere("ark:/99999/O'Malley");
    assert.ok(!sql.includes("'o'malley'"), 'raw unescaped single quote not present in canonical');
    assert.ok(sql.includes("o''malley"), 'single quote properly doubled (after lowercasing)');
});

test('pidSearchWhere: injection-safe — LIKE metacharacters escaped in localpart', () => {
    const sql = pidSearchWhere('igsn:test_50%boom');
    // _ and % must be backslash-escaped in the ILIKE pattern
    assert.ok(sql.includes('\\_'), 'underscore escaped');
    assert.ok(sql.includes('\\%'), 'percent escaped');
});
