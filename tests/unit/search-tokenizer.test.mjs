// JS tokenizer vs the shared regression set (#170) — the Python↔JS parity
// gate's JS half. The regression JSON's expected_tokens are generated from
// the Python implementation (tools/search_tokenizer.py); this suite passing
// means the two implementations agree on every entry.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { tokenize, MAX_TOKEN_LEN } from '../../assets/js/search_tokenizer.js';

const here = dirname(fileURLToPath(import.meta.url));
const REGRESSION = JSON.parse(
    readFileSync(join(here, '..', 'search_tokenizer_regression.json'), 'utf8'));

test('regression set is big enough (contract: >= 30)', () => {
    assert.ok(REGRESSION.length >= 30, `only ${REGRESSION.length} entries`);
});

for (const entry of REGRESSION) {
    test(`tokenize ${JSON.stringify(entry.input).slice(0, 40)}`, () => {
        assert.deepEqual(tokenize(entry.input), entry.expected_tokens);
    });
}

test('null/undefined/empty → []', () => {
    assert.deepEqual(tokenize(null), []);
    assert.deepEqual(tokenize(undefined), []);
    assert.deepEqual(tokenize(''), []);
});

test('length filter boundaries', () => {
    assert.deepEqual(tokenize('x'.repeat(MAX_TOKEN_LEN)), ['x'.repeat(MAX_TOKEN_LEN)]);
    assert.deepEqual(tokenize('x'.repeat(MAX_TOKEN_LEN + 1)), []);
});
