// Pure helpers extracted from explorer.qmd (issue #249, PR3).
// No closure over `viewer`/`db`/DOM — safe to unit-test under Node and to
// import into the Interactive Explorer's OJS runtime (see explorer.qmd).

// HTML-escape a value for safe interpolation into innerHTML.
export function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Split a free-text query into whitespace-delimited terms (no empties).
export function searchTerms(value) {
    return String(value || '').trim().split(/\s+/).filter(Boolean);
}

// Parse a numeric URL param with a default and optional clamping.
export function parseNum(val, def, min, max) {
    if (val == null) return def;
    const n = parseFloat(val);
    if (!Number.isFinite(n)) return def;
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
}

// Read a comma-separated URLSearchParams value into an array of trimmed,
// non-empty strings. Returns null when the key is absent, [] when present
// but empty.
export function csvParamValues(params, key) {
    if (!params.has(key)) return null;
    const raw = params.get(key) || '';
    if (raw.trim() === '') return [];
    return raw.split(',').map(s => s.trim()).filter(Boolean);
}

// Resolve a pid to its canonical resolver URL. All iSamples sources resolve
// via n2t.net: ARK pids (OpenContext, GEOME, Smithsonian) and IGSN pids
// (SESAR) alike.
export function sourceUrl(pid) {
    if (!pid) return null;
    return `https://n2t.net/${pid}`;
}

// Decode the explorer globe state from a URL hash fragment.
// `hashStr` defaults to `location.hash` for in-browser callers (every current
// call site is zero-arg); tests pass an explicit string so `location` is never
// referenced. Numeric fields are clamped to valid geographic / altitude ranges.
export function readHash(hashStr = location.hash) {
    const params = new URLSearchParams(hashStr.slice(1));
    return {
        v: parseInt(params.get('v')) || 0,
        lat: parseNum(params.get('lat'), null, -90, 90),
        lng: parseNum(params.get('lng'), null, -180, 180),
        alt: parseNum(params.get('alt'), null, 100, 40000000),
        heading: parseNum(params.get('heading'), 0, 0, 360),
        pitch: parseNum(params.get('pitch'), -90, -90, 0),
        mode: params.get('mode') || null,
        pid: params.get('pid') || null,
        h3: params.get('h3') || null,
        heatmap: params.get('heatmap') === '1',
    };
}
