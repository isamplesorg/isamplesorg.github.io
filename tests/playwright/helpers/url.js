// URL helpers for the Playwright suite.
//
// Why this exists: all specs in tests/playwright/ navigate to rendered
// pages on the site (explorer.html, tutorials/*.html, etc.) and accept
// a TEST_URL env var so they can run against:
//
//   - the dev / CI smoke gate's static server (`http://localhost:5860`)
//   - production (`https://isamples.org`)
//   - the fork-staging GitHub Pages URL
//     (`https://rdhyee.github.io/isamplesorg.github.io/`, with sub-path)
//
// The historical hand-rolled patterns had two latent gotchas:
//
//   1. Some specs called `page.goto('/explorer.html')` and relied on
//      Playwright's `baseURL` config. Playwright resolves an absolute
//      path against the ORIGIN of baseURL, so a sub-path TEST_URL like
//      `https://rdhyee.github.io/isamplesorg.github.io/` silently
//      resolves to `https://rdhyee.github.io/explorer.html` (404).
//
//   2. Specs that string-concat `${BASE_URL}${EXPLORER_PATH}` work on
//      sub-path TEST_URLs only when TEST_URL has no trailing slash.
//      A trailing slash produces `//explorer.html` — tolerated by some
//      servers, but not the intended URL shape.
//
// `siteUrl()` / `explorerUrl()` below collapse both gotchas: strip the
// trailing slash from BASE_URL once, then string-concat a leading-slash
// path. Same result whether TEST_URL is given with or without a trailing
// slash, and the sub-path is preserved on fork-staging.
//
// History: extracted 2026-05-27 from PR #238 (Codex round-1 review of
// the facet-viewport.spec.js URL fix recommended a shared helper rather
// than duplicating the fix into every spec).

const BASE_URL = (process.env.TEST_URL || 'http://localhost:5860').replace(/\/$/, '');

/** Build a URL on the rendered site.
 *
 * @param {string} path  Path on the site, should start with `/`
 *                       (e.g. `/explorer.html`, `/tutorials/parquet_cesium.html`).
 * @param {string} [suffix]  Optional hash or query suffix appended as-is
 *                           (e.g. `#v=1&lat=0&lng=0&alt=15000000`).
 * @returns {string}     Full URL ready for `page.goto()`.
 */
function siteUrl(path, suffix = '') {
    return `${BASE_URL}${path}${suffix}`;
}

/** Convenience for the most common case: a URL on the explorer page.
 *
 * @param {string} [suffix]  Optional hash or query suffix.
 * @returns {string}         Full URL ready for `page.goto()`.
 */
function explorerUrl(suffix = '') {
    return siteUrl('/explorer.html', suffix);
}

module.exports = { BASE_URL, siteUrl, explorerUrl };
