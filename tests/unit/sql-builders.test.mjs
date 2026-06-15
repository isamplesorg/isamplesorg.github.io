// Unit tests for assets/js/sql-builders.js (issue #249, PR3).
// Run: node --test tests/unit/   (Node built-ins only, no install)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    escSql, escapeIlikePattern, textSearchWhere, textSearchScore,
} from '../../assets/js/sql-builders.js';

test('escSql doubles single quotes and stringifies', () => {
    assert.equal(escSql("O'Brien"), "O''Brien");
    assert.equal(escSql("plain"), "plain");
    assert.equal(escSql("''"), "''''");
    assert.equal(escSql(123), "123");
});

test('escapeIlikePattern backslash-escapes LIKE metachars after SQL-escaping', () => {
    assert.equal(escapeIlikePattern("100%"), "100\\%");
    assert.equal(escapeIlikePattern("a_b"), "a\\_b");
    // a single backslash becomes an escaped backslash
    assert.equal(escapeIlikePattern("a\\b"), "a\\\\b");
    // single-quote doubling (escSql) happens BEFORE metachar escaping
    assert.equal(escapeIlikePattern("O'Brien%"), "O''Brien\\%");
    assert.equal(escapeIlikePattern("plain"), "plain");
});

test('textSearchWhere: terms AND-ed, columns OR-ed, ESCAPE clause present', () => {
    assert.equal(
        textSearchWhere(['cat'], ['label', 'descr']),
        "(label ILIKE '%cat%' ESCAPE '\\' OR descr ILIKE '%cat%' ESCAPE '\\')"
    );
    assert.equal(
        textSearchWhere(['cat', 'dog'], ['label']),
        "(label ILIKE '%cat%' ESCAPE '\\') AND (label ILIKE '%dog%' ESCAPE '\\')"
    );
});

test('textSearchScore: empty terms -> "0"; weighted CASE sum otherwise', () => {
    assert.equal(textSearchScore([], [{ col: 'label', weight: 3 }]), '0');
    assert.equal(
        textSearchScore(['cat'], [{ col: 'label', weight: 3 }, { col: 'descr', weight: 1 }]),
        "(CASE WHEN label ILIKE '%cat%' ESCAPE '\\' THEN 3 ELSE 0 END + CASE WHEN descr ILIKE '%cat%' ESCAPE '\\' THEN 1 ELSE 0 END)"
    );
});

test('textSearchScore escapes terms (injection-safe)', () => {
    assert.equal(
        textSearchScore(["O'Brien"], [{ col: 'label', weight: 1 }]),
        "(CASE WHEN label ILIKE '%O''Brien%' ESCAPE '\\' THEN 1 ELSE 0 END)"
    );
});
