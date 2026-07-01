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

// ---------------------------------------------------------------------------
// PID search helpers (issues #278 + #26)
// ---------------------------------------------------------------------------

// Resolver-URL prefixes we strip before comparing (order matters: longest first).
// n2t.net and arks.org are ARK resolvers; doi.org handles DOIs; hdl.handle.net
// is the Handle System resolver. We only strip one prefix per call.
const RESOLVER_RE = /^https?:\/\/(n2t\.net|arks\.org|doi\.org|hdl\.handle\.net)\//i;

// Canonicalize a PID for client-side comparison:
//   1. Lowercase the whole string.
//   2. Strip a leading resolver-URL prefix (n2t.net, doi.org, etc.).
//   3. Collapse classic-ARK `ark:/` → `ark:` (issue #26: modern vs classic ARK).
//      The slash after the colon is not part of the ARK NAAN — both forms
//      (`ark:/28722/…` and `ark:28722/…`) refer to the same identifier.
// IGSN, DOI, and other scheme-prefixed identifiers are lowercased but otherwise
// left intact so they match the stored values (which are also lowercased here).
export function canonicalizePid(value) {
    let v = String(value).trim().toLowerCase();
    v = v.replace(RESOLVER_RE, '');        // strip resolver prefix if present
    v = v.replace(/^ark:\//, 'ark:');     // collapse classic → modern ARK form
    return v;
}

// Heuristic: does this search term look like a PID rather than plain text?
// Returns true when the term carries an explicit PID scheme or resolver URL,
// so we can route it through PID-aware matching without changing plain-text
// search behaviour.
//
// Covered cases:
//   pid:…   — explicit escape hatch: scheme-agnostic substring match on pid col
//   ark:…   — both classic (ark:/) and modern (ark:) forms
//   igsn:…  — SESAR-style identifiers
//   doi:…   — DOI scheme
//   10.…    — bare DOI (starts with "10." as DataCite convention)
//   https?://n2t.net/…, https?://doi.org/…, etc. — resolver URLs
export function looksLikePid(term) {
    const t = String(term).trim().toLowerCase();
    return (
        t.startsWith('pid:') ||          // explicit escape hatch (see pidSearchWhere)
        t.startsWith('ark:') ||
        t.startsWith('igsn:') ||
        t.startsWith('doi:') ||
        /^10\./.test(t) ||               // bare DOI like 10.5281/zenodo.123
        RESOLVER_RE.test(t)              // resolver URL
    );
}

// Build a SQL predicate fragment for PID matching.
//
// Two code paths:
//
// 1. `pid:` prefix (scheme-agnostic escape hatch) — user typed e.g. `pid:IEGIL000C`
//    or `pid:k2000027w` to find a sample by a bare fragment without knowing the
//    scheme. Emits a single ILIKE substring match against the pid column:
//      pid ILIKE '%<fragment>%' ESCAPE '\'
//    DuckDB's ILIKE is already case-insensitive so no LOWER is needed. The
//    remainder after "pid:" is passed through escapeIlikePattern for safety.
//    The canonical exact-match arm is intentionally skipped — the substring
//    already spans all scheme variants.
//
// 2. Scheme-bearing / resolver-URL terms (ark:, igsn:, doi:, 10., https://…) —
//    two-sided normalisation so stored format doesn't matter:
//      A. Exact-match: LOWER(REPLACE(pid, 'ark:/', 'ark:')) = '<canonical>'
//         Handles stored-side ARK-slash collapse and case normalisation.
//         No resolver-URL prefix in stored data, so only REPLACE+LOWER needed.
//      B. Local-part fallback: pid ILIKE '%<localpart>%' ESCAPE '\'
//         The part after the last '/' (or the whole canonical if no '/')
//         catches bare local identifiers that coincide with the query.
//    Both predicates OR-ed.
//
// All user input passes through escSql / escapeIlikePattern — no raw interpolation.
export function pidSearchWhere(rawTerm) {
    const trimmed = String(rawTerm).trim();

    // --- Path 1: pid: escape hatch ---
    if (trimmed.toLowerCase().startsWith('pid:')) {
        const fragment = trimmed.slice(4);   // strip the "pid:" prefix (any case)
        const fragEsc = escapeIlikePattern(fragment);
        // Single substring ILIKE — no scheme assumption, ILIKE is case-insensitive.
        return `pid ILIKE '%${fragEsc}%' ESCAPE '\\'`;
    }

    // --- Path 2: scheme-bearing / resolver-URL term ---
    const canonical = canonicalizePid(trimmed);
    // Safe interpolation via escSql (no raw user input in the SQL string).
    const canonEsc = escSql(canonical);

    // Stored-side normalisation in SQL: lowercase + collapse ark:/ → ark:
    // (DuckDB's REPLACE is case-sensitive on the search string, so we LOWER
    // first, then replace the already-lowercased prefix.)
    const storedNorm = `LOWER(REPLACE(pid, 'ark:/', 'ark:'))`;

    // Local-part fallback: strip everything up to and including the last '/'
    // in the *canonical* form, leaving the bare local identifier.
    const slashIdx = canonical.lastIndexOf('/');
    const localPart = slashIdx >= 0 ? canonical.slice(slashIdx + 1) : canonical;
    const localEsc = escapeIlikePattern(localPart);

    // Combine: exact normalised match OR bare-localpart substring match.
    // The substring match is deliberately narrow (must appear somewhere in pid)
    // so it doesn't produce false hits on label/description columns.
    return `(${storedNorm} = '${canonEsc}' OR pid ILIKE '%${localEsc}%' ESCAPE '\\')`;
}
