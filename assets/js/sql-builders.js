// Pure SQL-string builders extracted from explorer.qmd (issue #249, PR3).
// No closure over `viewer`/`db`/DOM — safe to unit-test under Node and to
// import into the Interactive Explorer's OJS runtime (see explorer.qmd).
//
// Internal dependency chain: textSearch* -> escapeIlikePattern -> escSql.
// Each function references the module-local sibling directly, so importing
// these into OJS does NOT create reactive edges between the bound cells.

// Double single-quotes for safe interpolation into a SQL string literal.
export function escSql(value) {
    return String(value).replace(/'/g, "''");
}

// Escape a value for use inside an ILIKE '%...%' pattern with ESCAPE '\'.
// First SQL-escapes single quotes (escSql), then backslash-escapes the LIKE
// metacharacters \ % _ so they match literally.
export function escapeIlikePattern(value) {
    return escSql(value).replace(/[\\%_]/g, "\\$&");
}

// Build a WHERE fragment: every term must match at least one column
// (terms AND-ed, columns OR-ed within a term).
export function textSearchWhere(terms, columns) {
    return terms.map(raw => {
        const term = escapeIlikePattern(raw);
        const checks = columns.map(col => `${col} ILIKE '%${term}%' ESCAPE '\\'`);
        return `(${checks.join(' OR ')})`;
    }).join(' AND ');
}

// Build a relevance-score expression: sum of per-term, per-weighted-column
// CASE contributions. Returns '0' when there are no terms.
export function textSearchScore(terms, weightedColumns) {
    if (!terms.length) return '0';
    return terms.map(raw => {
        const term = escapeIlikePattern(raw);
        return weightedColumns.map(({ col, weight }) =>
            `CASE WHEN ${col} ILIKE '%${term}%' ESCAPE '\\' THEN ${weight} ELSE 0 END`
        ).join(' + ');
    }).map(score => `(${score})`).join(' + ');
}
